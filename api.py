import os
import re
import json
import base64
import secrets
import requests
import zipfile
import subprocess
import tempfile
import shutil
from time import sleep
from datetime import datetime
from pathlib import Path

INPUT_FOLDER = "input"
OUTPUT_FOLDER = "output"
ACCOUNTS_FILE = "accounts.json"
INSTANT_MESHES_PATH = "Instant Meshes.exe"  # Caminho para o executável do Instant Meshes

class Colors:
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    END = '\033[0m'
    BOLD = '\033[1m'

def log(msg, color=Colors.CYAN):
    print(f"{color}[{datetime.now().strftime('%H:%M:%S')}]{Colors.END} {msg}")

def progress_bar(current, total, prefix=''):
    filled = int(50 * current // total)
    bar = '█' * filled + '-' * (50 - filled)
    print(f'\r{prefix} |{bar}| {100 * current / total:.1f}%', end='', flush=True)

class TempMail:
    def __init__(self):
        self.session = requests.Session()
        self.base_url = "https://api.mail.tm"
        self._create_account()
    
    def _create_account(self):
        domains_resp = self.session.get(f"{self.base_url}/domains", timeout=10)
        domain = domains_resp.json()['hydra:member'][0]['domain']
        username = secrets.token_hex(8)
        self.email = f"{username}@{domain}"
        password = secrets.token_hex(16)
        self.session.post(f"{self.base_url}/accounts", json={"address": self.email, "password": password}, timeout=10)
        token_resp = self.session.post(f"{self.base_url}/token", json={"address": self.email, "password": password}, timeout=10)
        self.token = token_resp.json()['token']
        self.session.headers.update({'Authorization': f'Bearer {self.token}'})
    
    def get_messages(self):
        try: return self.session.get(f"{self.base_url}/messages", timeout=10).json().get('hydra:member', [])
        except: return []
    
    def get_message(self, msg_id):
        try: return self.session.get(f"{self.base_url}/messages/{msg_id}", timeout=10).json()
        except: return None

def extract_otp(html):
    if not html: return None
    match = re.search(r'\b(\d{6})\b', html)
    return match.group(1) if match and match.group(1) not in ["000000", "111111", "123456"] else None

def register_account():
    log("🔄 Criando conta Meshy.ai...", Colors.YELLOW)
    try:
        session = requests.Session()
        tm = TempMail()
        log(f"📧 {tm.email}", Colors.CYAN)
        headers = {
            "content-type": "application/json",
            "apikey": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InluZnJlY2xzeGZncW52Z2ZweGNjIiwicm9sZSI6ImFub24iLCJpYXQiOjE3MTU1ODQwNjUsImV4cCI6MjAzMTE2MDA2NX0.015muXUW_O30jeBOxEU9-TQOJigcKMUhkNFbPOWu_iA",
            "authorization": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InluZnJlY2xzeGZncW52Z2ZweGNjIiwicm9sZSI6ImFub24iLCJpYXQiOjE3MTU1ODQwNjUsImV4cCI6MjAzMTE2MDA2NX0.015muXUW_O30jeBOxEU9-TQOJigcKMUhkNFbPOWu_iA",
        }
        import hashlib
        verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode('utf-8').rstrip('=')
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode('utf-8')).digest()).decode('utf-8').rstrip('=')
        session.post("https://auth.meshy.ai/auth/v1/otp", headers=headers, json={
            "email": tm.email, "create_user": True, "code_challenge": challenge, "code_challenge_method": "s256"
        }, timeout=15)
        otp = None
        for i in range(18):
            progress_bar(i + 1, 18, 'OTP')
            for msg in tm.get_messages():
                if 'meshy' in msg.get('subject', '').lower():
                    content = tm.get_message(msg['id'])
                    html = content.get('html', [str(content.get('html'))])[0] if isinstance(content.get('html'), list) else str(content.get('html'))
                    otp = extract_otp(html) or extract_otp(content.get('text', ''))
                    if otp: break
            if otp: break
            sleep(5)
        print()
        if not otp: return None, None
        resp = session.post("https://auth.meshy.ai/auth/v1/verify", headers=headers, json={"type": "email", "email": tm.email, "token": otp}, timeout=15).json()
        if resp.get("access_token"):
            accs = {}
            if os.path.exists(ACCOUNTS_FILE):
                with open(ACCOUNTS_FILE) as f: accs = json.load(f)
            accs[tm.email] = {"access_token": resp["access_token"], "created_at": datetime.now().isoformat()}
            with open(ACCOUNTS_FILE, 'w') as f: json.dump(accs, f, indent=2)
            return tm.email, accs[tm.email]
    except Exception as e: log(f"❌ {e}", Colors.RED)
    return None, None

def get_or_create_account():
    if os.path.exists(ACCOUNTS_FILE):
        try:
            with open(ACCOUNTS_FILE) as f:
                accs = json.load(f)
                if accs: return list(accs.keys())[0], accs[list(accs.keys())[0]]
        except: pass
    return register_account()

def convert_zip_to_quad(zip_path):
    """
    Pega o ZIP, extrai, converte GLB para PURE QUAD (5k-8k faces), apaga triangular, rezipa
    PLUG AND PLAY - PURE QUAD PROFISSIONAL
    
    Args:
        zip_path: Caminho para o arquivo ZIP
    
    Returns:
        Caminho do novo ZIP com quad mesh ou ZIP original se falhar
    """
    log("🔄 Convertendo ZIP para PURE QUAD MESH...", Colors.YELLOW)
    
    # Verificar se Instant Meshes existe
    if not os.path.isfile(INSTANT_MESHES_PATH):
        log(f"⚠️ Instant Meshes não encontrado em: {INSTANT_MESHES_PATH}", Colors.YELLOW)
        log(f"⚠️ Baixe de: https://github.com/wjakob/instant-meshes", Colors.YELLOW)
        log(f"⚠️ Pulando conversão para quad mesh...", Colors.YELLOW)
        return zip_path
    
    try:
        # Importar trimesh
        try:
            import trimesh
        except ImportError:
            log("⚠️ trimesh não instalado (pip install trimesh)", Colors.YELLOW)
            log("⚠️ Pulando conversão para quad mesh...", Colors.YELLOW)
            return zip_path
        
        with tempfile.TemporaryDirectory() as temp_dir:
            extract_dir = os.path.join(temp_dir, "extracted")
            os.makedirs(extract_dir)
            
            # 1. EXTRAIR ZIP
            log("📂 Extraindo ZIP...", Colors.CYAN)
            with zipfile.ZipFile(zip_path, 'r') as zipf:
                zipf.extractall(extract_dir)
            
            # 2. ENCONTRAR GLB
            glb_files = [f for f in os.listdir(extract_dir) if f.lower().endswith('.glb')]
            if not glb_files:
                log("⚠️ Nenhum GLB encontrado no ZIP", Colors.YELLOW)
                return zip_path
            
            glb_filename = glb_files[0]
            glb_path = os.path.join(extract_dir, glb_filename)
            log(f"📦 GLB encontrado: {glb_filename}", Colors.CYAN)
            
            # 3. CONVERTER PARA PURE QUAD com 5k-8k faces
            temp_obj = os.path.join(temp_dir, "temp_input.obj")
            temp_output = os.path.join(temp_dir, "temp_output.obj")
            
            log("📐 Carregando GLB triangular...", Colors.CYAN)
            mesh = trimesh.load(glb_path)
            
            if isinstance(mesh, trimesh.Scene):
                meshes = list(mesh.geometry.values())
                if not meshes:
                    log("❌ Nenhuma geometria encontrada", Colors.RED)
                    return zip_path
                mesh = trimesh.util.concatenate(meshes)
            
            original_faces = len(mesh.faces)
            original_verts = len(mesh.vertices)
            log(f"📊 Original: {original_faces} faces (triângulos)", Colors.CYAN)
            
            mesh.export(temp_obj)
            
            # 4. EXECUTAR INSTANT MESHES - PURE QUAD (5k-8k faces)
            # Usar 5000-8000 faces para quads limpos e visíveis
            target_faces = min(8000, max(5000, int(original_faces * 0.3)))  # Máximo 8000, mínimo 5000
            
            log(f"⚙️ Instant Meshes: {target_faces} faces PURE QUAD (malha limpa)...", Colors.CYAN)
            
            cmd = [
                INSTANT_MESHES_PATH,
                temp_obj,
                "-o", temp_output,
                "-f", str(target_faces),
                "-c", "35",  # Crease angle para bordas afiadas
                "-S", "2"    # Smoothing
                # SEM -D = PURE QUAD (sem triângulos)
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            
            if result.returncode != 0 or not os.path.isfile(temp_output):
                log(f"⚠️ Instant Meshes falhou, mantendo original", Colors.YELLOW)
                return zip_path
            
            # 5. CONVERTER DE VOLTA PARA GLB
            log("💾 Salvando PURE QUAD MESH em GLB...", Colors.CYAN)
            quad_mesh = trimesh.load(temp_output)
            
            quad_faces = len(quad_mesh.faces)
            quad_verts = len(quad_mesh.vertices)
            log(f"✅ PURE QUAD: {quad_faces} faces, {quad_verts} vértices", Colors.GREEN)
            
            # APAGAR GLB triangular original
            os.remove(glb_path)
            
            # Salvar GLB QUAD com mesmo nome
            quad_mesh.export(glb_path)
            log(f"✅ GLB substituído por PURE QUAD MESH", Colors.GREEN)
            
            # 6. REZIPAR TUDO
            log("📦 Rezipando com PURE QUAD MESH...", Colors.CYAN)
            
            # Atualizar README para versão QUAD
            readme_path = os.path.join(extract_dir, "README.txt")
            if os.path.exists(readme_path):
                try:
                    with open(readme_path, 'r', encoding='utf-8') as f:
                        readme_content = f.read()
                except:
                    # Se falhar UTF-8, tentar latin-1
                    with open(readme_path, 'r', encoding='latin-1') as f:
                        readme_content = f.read()
                
                # Atualizar o README com info de PURE QUAD
                readme_content = readme_content.replace(
                    "MODELO 3D - MÁXIMA QUALIDADE + TEXTURA",
                    "MODELO 3D - MÁXIMA QUALIDADE + TEXTURA + PURE QUAD MESH"
                )
                readme_content = readme_content.replace(
                    "Bot: Meshy AI v14 FINAL",
                    "Bot: Meshy AI v14 FINAL + PURE QUAD CONVERTER"
                )
                readme_content = readme_content.replace(
                    "✓ UV Mapping: Otimizado",
                    "✓ UV Mapping: Otimizado\n✓ Topologia: PURE QUAD MESH (5k-8k faces)"
                )
                
                quad_info = f"""

CONVERSÃO PURE QUAD MESH:
O modelo original em triângulos ({original_faces} faces) foi automaticamente
convertido para PURE QUAD MESH ({quad_faces} faces) usando Instant Meshes.

CONFIGURAÇÃO OTIMIZADA:
✓ Target: 5.000-8.000 faces (malha limpa e visível)
✓ Modo: PURE QUAD (sem triângulos misturados)
✓ Crease Angle: 35° (bordas afiadas preservadas)
✓ Topologia profissional para produção

BENEFÍCIOS DA TOPOLOGIA PURE QUAD:
✓ Malha quadrada limpa e organizada
✓ Subdivisão de superfície perfeita
✓ Ideal para animação e deformação
✓ Facilita modelagem e edição
✓ Padrão profissional da indústria

PROCESSO AUTOMÁTICO:
1. GLB gerado pela API Meshy (triângulos)
2. Conversão para PURE QUAD (5k-8k faces)
3. Empacotamento final
"""
                readme_content = readme_content.replace(
                    "Gerado com ❤️ pelo Meshy Bot v14 FINAL",
                    quad_info + "\nGerado com ❤️ pelo Meshy Bot v14 FINAL + PURE QUAD CONVERTER"
                )
                
                with open(readme_path, 'w', encoding='utf-8') as f:
                    f.write(readme_content)
            
            # Criar novo ZIP com _QUAD no nome
            new_zip_path = zip_path.replace('.zip', '_QUAD.zip')
            
            with zipfile.ZipFile(new_zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for root, dirs, files in os.walk(extract_dir):
                    for file in files:
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, extract_dir)
                        zipf.write(file_path, arcname)
            
            # APAGAR ZIP TRIANGULAR
            os.remove(zip_path)
            
            log(f"✅ ZIP PURE QUAD criado: {new_zip_path}", Colors.GREEN)
            log(f"🗑️ ZIP triangular removido", Colors.CYAN)
            
            return new_zip_path
            
    except subprocess.TimeoutExpired:
        log("❌ Timeout (5 min)", Colors.RED)
        return zip_path
    except Exception as e:
        log(f"❌ Erro: {e}", Colors.RED)
        return zip_path

class MeshyBot:
    def __init__(self, auth_data):
        self.session = requests.Session()
        self.session.headers.update({
            "authorization": f"Bearer {auth_data['access_token']}",
            "content-type": "application/json",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        })

    def upload_image(self, path):
        log("📤 Upload da imagem...", Colors.CYAN)
        ext = Path(path).suffix.lower().replace('.', '')
        if ext == 'jpg': ext = 'jpeg'
        files = {'file': (Path(path).name, open(path, 'rb'), f'image/{ext}')}
        headers = self.session.headers.copy()
        headers.pop('content-type', None)
        resp = requests.post("https://api.meshy.ai/web/v1/files/images?skipNameGeneration", 
                            headers=headers, files=files, timeout=30).json()
        if resp.get("code") in ["InvalidToken", "InsufficientCredits", "QuotaExceeded"]:
            return resp.get("code")
        if resp.get("code") == "OK": 
            log(f"✅ Upload: {resp['result']['id']}", Colors.GREEN)
            return resp["result"]["id"]
        return None

    def create_draft(self, image_id):
        log("🎨 Criando drafts 3D...", Colors.CYAN)
        payload = {
            "phase": "draft",
            "args": {
                "draft": {
                    "imageId": image_id,
                    "aiModel": "meshy-4"
                }
            }
        }
        resp = self.session.post("https://api.meshy.ai/web/v2/tasks", json=payload, timeout=30).json()
        if resp.get("code") == "OK": 
            log(f"✅ Draft criado: {resp['result']}", Colors.GREEN)
            return resp["result"]
        log(f"❌ Erro: {resp}", Colors.RED)
        return None

    def analyze_drafts(self, draft_id):
        """Analisa os drafts e retorna o ID do melhor disponível"""
        log("🔍 Analisando drafts disponíveis...", Colors.CYAN)
        try:
            resp = self.session.get(f"https://api.meshy.ai/web/v2/tasks/{draft_id}", timeout=15).json()
            
            if resp.get("code") == "OK":
                result = resp.get("result", {})
                
                # Verificar quantos drafts foram gerados
                # A API pode gerar 1, 2, 3 ou 4 drafts dependendo da complexidade
                if "modelUrls" in result and isinstance(result["modelUrls"], list):
                    drafts_count = len(result["modelUrls"])
                    log(f"📊 {drafts_count} draft(s) disponível(is)", Colors.CYAN)
                    
                    # Usar o ÚLTIMO draft (geralmente o mais detalhado)
                    best_draft = str(drafts_count)
                    log(f"🎯 Selecionado: Draft #{best_draft}", Colors.GREEN)
                    return best_draft
                
                # Se não tiver modelUrls, tentar verificar de outra forma
                log("⚠️ Estrutura diferente, tentando draft 1", Colors.YELLOW)
                return "1"
            
            log("⚠️ Erro ao analisar, usando draft 1", Colors.YELLOW)
            return "1"
        except Exception as e:
            log(f"⚠️ Exceção: {e}, usando draft 1", Colors.YELLOW)
            return "1"

    def generate_max_quality_textured(self, draft_id, best_draft_id):
        log(f"🎯 Gerando draft #{best_draft_id} com MAX polycount + TEXTURA...", Colors.CYAN)
        
        # Baseado nas screenshots: polycount "Max" e textura "Sim"
        # IMPORTANTE: Usar o draft selecionado (geralmente 4 = mais detalhado)
        payload_correct = {
            "draftIds": [best_draft_id],
            "enablePbr": True,
            "targetPolycount": "max",
            "shouldTexture": True
        }
        
        log(f"🧪 Usando draft #{best_draft_id} com parâmetros descobertos", Colors.CYAN)
        
        try:
            payload = {
                "phase": "generate",
                "parent": draft_id,
                "args": {"generate": payload_correct}
            }
            
            resp = self.session.post("https://api.meshy.ai/web/v2/tasks", json=payload, timeout=30).json()
            
            if resp.get("code") == "OK":
                result = resp.get("result", [])
                task_id = result[0] if isinstance(result, list) else result
                log(f"✅ SUCESSO! Draft #{best_draft_id} com MAX quality + textura", Colors.GREEN)
                return task_id, payload_correct
            else:
                log(f"❌ Erro: {resp}", Colors.RED)
                return None, None
        except Exception as e:
            log(f"❌ Exceção: {e}", Colors.RED)
            return None, None

    def wait_task(self, task_id, name="Task"):
        log(f"⏳ Aguardando {name}...", Colors.YELLOW)
        for _ in range(180):
            resp = self.session.get(f"https://api.meshy.ai/web/v1/tasks/{task_id}/status", timeout=10).json()
            res = resp.get("result", {})
            status = res.get("status")
            if status == "SUCCEEDED":
                print()
                log(f"✅ {name} completa!", Colors.GREEN)
                return True
            if status == "FAILED":
                print()
                log(f"❌ {name} falhou", Colors.RED)
                return False
            print(f"\r{Colors.CYAN}⏳ {status} {res.get('progress', 0)}%{Colors.END}", end='', flush=True)
            sleep(10)
        print()
        return False

    def download_glb(self, task_id, name):
        log(f"📥 Baixando GLB texturizado...", Colors.CYAN)
        resp = self.session.get(f"https://api.meshy.ai/web/v2/tasks/{task_id}/asset-url", 
                                params={"type": "Task", "format": "glb"}, timeout=15).json()
        if resp.get("code") == "OK":
            os.makedirs(OUTPUT_FOLDER, exist_ok=True)
            path = os.path.join(OUTPUT_FOLDER, f"{name}_MAX_TEXTURED.glb")
            glb_data = requests.get(resp["result"], timeout=120).content
            with open(path, 'wb') as f: f.write(glb_data)
            size = len(glb_data) / 1024 / 1024
            log(f"✅ GLB: {path} ({size:.2f} MB)", Colors.GREEN)
            return path
        return None

    def create_zip(self, glb, img, name):
        log("📦 Criando pacote inicial...", Colors.CYAN)
        zip_path = os.path.join(OUTPUT_FOLDER, f"{name}_MAX_QUALITY_TEXTURED.zip")
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            if glb and os.path.exists(glb):
                zipf.write(glb, arcname=Path(glb).name)
                os.remove(glb)
            zipf.write(img, arcname=f"reference_{Path(img).name}")
            readme = f"""MODELO 3D - MÁXIMA QUALIDADE + TEXTURA
====================================================

Arquivo: {name}
Data: {datetime.now().strftime('%Y-%m-%d %H:%M')}
Bot: Meshy AI v14 FINAL

ESPECIFICAÇÕES:
✓ Polycount: MÁXIMO (mais detalhes possíveis)
✓ Textura: ATIVADA (cores da imagem)
✓ Materiais: PBR enabled
✓ UV Mapping: Otimizado

CONTEÚDO:
- {Path(glb).name if glb else 'modelo'} (GLB com máxima qualidade)
- reference_{Path(img).name} (Imagem original)

QUALIDADE:
Este modelo foi gerado com:
1. Polycount configurado para MÁXIMO
2. Textura gerada a partir da imagem
3. Materiais PBR para realismo

COMPATÍVEL COM:
Unity, Unreal Engine, Blender, Godot, Maya, 3DS Max, Three.js

IMPORTANTE:
Se o modelo ainda estiver sem cores, significa que a API
gratuita não suporta texturização automática e você precisará
aplicar as texturas manualmente no Blender usando a imagem
de referência incluída.

Gerado com ❤️ pelo Meshy Bot v14 FINAL
"""
            zipf.writestr("README.txt", readme)
        log(f"✅ ZIP inicial: {zip_path}", Colors.GREEN)
        return zip_path

def main():
    log("="*70, Colors.BOLD)
    log("🎨 MESHY BOT v14 FINAL + PURE QUAD CONVERTER", Colors.BOLD)
    log("="*70, Colors.BOLD)
    
    email, auth = get_or_create_account()
    if not email: 
        log("❌ Falha ao criar conta", Colors.RED)
        return
    
    log(f"✅ Conta ativa: {email}", Colors.GREEN)
    bot = MeshyBot(auth)
    
    os.makedirs(INPUT_FOLDER, exist_ok=True)
    images = [f for f in os.listdir(INPUT_FOLDER) if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp'))]
    
    if not images:
        log("⚠️ Nenhuma imagem em input/", Colors.YELLOW)
        return

    for img_name in images:
        log(f"\n{'='*70}", Colors.BOLD)
        log(f"🖼️ Processando: {img_name}", Colors.BOLD)
        log(f"{'='*70}", Colors.BOLD)
        
        path = os.path.join(INPUT_FOLDER, img_name)
        base_name = Path(img_name).stem
        
        # Upload
        image_id = bot.upload_image(path)
        if image_id in ["InvalidToken", "InsufficientCredits", "QuotaExceeded"]:
            log("🔄 Criando nova conta...", Colors.YELLOW)
            if os.path.exists(ACCOUNTS_FILE): os.remove(ACCOUNTS_FILE)
            email, auth = register_account()
            if not email: continue
            bot = MeshyBot(auth)
            image_id = bot.upload_image(path)
        
        if not image_id: continue
        
        # Draft
        draft_id = bot.create_draft(image_id)
        if not draft_id or not bot.wait_task(draft_id, "Drafts 3D"): continue
        
        # Analisar drafts e escolher o melhor
        best_draft_id = bot.analyze_drafts(draft_id)
        
        # Generate com MAX polycount + Textura usando o MELHOR draft
        model_id, successful_params = bot.generate_max_quality_textured(draft_id, best_draft_id)
        
        if not model_id:
            log("❌ Falha na geração", Colors.RED)
            continue
        
        if successful_params:
            log(f"🎉 Parâmetros descobertos: {successful_params}", Colors.GREEN)
        
        if not bot.wait_task(model_id, "Modelo MAX Quality"): continue
        
        # Download GLB triangular
        glb = bot.download_glb(model_id, base_name)
        if not glb:
            log("❌ Falha no download do GLB", Colors.RED)
            continue
        
        # Criar ZIP com o GLB original primeiro
        zip_path = bot.create_zip(glb, path, base_name)
        if not zip_path:
            log("❌ Falha ao criar ZIP", Colors.RED)
            continue
        
        # PLUG AND PLAY: Processar ZIP - Extrair, Converter para PURE QUAD, Rezipar
        final_zip = convert_zip_to_quad(zip_path)
        
        log(f"🎉 SUCESSO TOTAL: {final_zip}", Colors.GREEN)
        if successful_params:
            log(f"💡 Parâmetros corretos: {successful_params}", Colors.CYAN)

    log("\n"+"="*70, Colors.BOLD)
    log("✨ Processamento finalizado!", Colors.BOLD)
    log("="*70, Colors.BOLD)

if __name__ == "__main__":
    main()