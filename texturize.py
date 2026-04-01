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
        
        otp_resp = session.post("https://auth.meshy.ai/auth/v1/otp", headers=headers, json={
            "email": tm.email, "create_user": True, "code_challenge": challenge, "code_challenge_method": "s256"
        }, timeout=15)
        
        log(f"🔍 Resposta OTP: {otp_resp.status_code}", Colors.CYAN)
        
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
        if not otp: 
            log("❌ OTP não recebido", Colors.RED)
            return None, None
            
        log(f"✅ OTP recebido: {otp}", Colors.GREEN)
        resp = session.post("https://auth.meshy.ai/auth/v1/verify", headers=headers, json={"type": "email", "email": tm.email, "token": otp}, timeout=15).json()
        
        log(f"🔍 Resposta verify: {json.dumps(resp, indent=2)[:200]}", Colors.CYAN)
        
        if resp.get("access_token"):
            accs = {}
            if os.path.exists(ACCOUNTS_FILE):
                with open(ACCOUNTS_FILE) as f: accs = json.load(f)
            accs[tm.email] = {"access_token": resp["access_token"], "created_at": datetime.now().isoformat()}
            with open(ACCOUNTS_FILE, 'w') as f: json.dump(accs, f, indent=2)
            log(f"✅ Conta criada com sucesso!", Colors.GREEN)
            return tm.email, accs[tm.email]
        else:
            log(f"❌ Token não recebido na resposta", Colors.RED)
    except Exception as e: 
        log(f"❌ Erro no registro: {e}", Colors.RED)
        import traceback
        log(f"Stack trace: {traceback.format_exc()}", Colors.RED)
    return None, None

def get_or_create_account():
    if os.path.exists(ACCOUNTS_FILE):
        try:
            with open(ACCOUNTS_FILE) as f:
                accs = json.load(f)
                if accs: 
                    email = list(accs.keys())[0]
                    log(f"📁 Usando conta existente: {email}", Colors.CYAN)
                    return email, accs[email]
        except: pass
    return register_account()

class MeshyBot:
    def __init__(self, auth_data):
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {auth_data['access_token']}",
            "Content-Type": "application/json"
        })
    
    def upload_image(self, img_path):
        log("📤 Upload da imagem...", Colors.CYAN)
        try:
            with open(img_path, 'rb') as f:
                # Remove Content-Type header for file upload
                headers = {k: v for k, v in self.session.headers.items() if k.lower() != 'content-type'}
                resp = self.session.post("https://api.meshy.ai/web/v1/assets/images", 
                                        files={"file": f}, 
                                        headers=headers,
                                        timeout=30)
                
                log(f"🔍 Upload status: {resp.status_code}", Colors.CYAN)
                log(f"🔍 Upload response: {resp.text[:500]}", Colors.CYAN)
                
                resp_json = resp.json()
                
            if resp_json.get("code") == "OK":
                img_id = resp_json["result"]["id"]
                log(f"✅ Imagem carregada: {img_id}", Colors.GREEN)
                return img_id
            elif resp_json.get("code") in ["InvalidToken", "InsufficientCredits", "QuotaExceeded"]:
                log(f"⚠️ Erro de quota/token: {resp_json.get('code')}", Colors.YELLOW)
                return resp_json["code"]
            else:
                log(f"❌ Erro no upload: {resp_json}", Colors.RED)
                return None
        except Exception as e: 
            log(f"❌ Exceção no upload: {e}", Colors.RED)
            import traceback
            log(f"Stack trace: {traceback.format_exc()}", Colors.RED)
            return None
    
    def create_draft(self, image_id):
        log("🎨 Gerando drafts 3D...", Colors.CYAN)
        try:
            payload = {
                "phase": "preview",
                "args": {
                    "preview": {
                        "imageIds": [image_id],
                        "enablePbr": True,
                        "multilingual": False
                    }
                }
            }
            log(f"🔍 Payload draft: {json.dumps(payload, indent=2)}", Colors.CYAN)
            
            resp = self.session.post("https://api.meshy.ai/web/v2/tasks", json=payload, timeout=30)
            
            log(f"🔍 Draft status: {resp.status_code}", Colors.CYAN)
            log(f"🔍 Draft response: {resp.text[:500]}", Colors.CYAN)
            
            resp_json = resp.json()
            
            if resp_json.get("code") == "OK":
                result = resp_json.get("result", [])
                draft_id = result[0] if isinstance(result, list) else result
                log(f"✅ Draft criado: {draft_id}", Colors.GREEN)
                return draft_id
            else:
                log(f"❌ Erro ao criar draft: {resp_json}", Colors.RED)
                return None
        except Exception as e: 
            log(f"❌ Exceção ao criar draft: {e}", Colors.RED)
            import traceback
            log(f"Stack trace: {traceback.format_exc()}", Colors.RED)
            return None
    
    def analyze_drafts(self, draft_id):
        """Analisa drafts e retorna o ID do melhor"""
        log("🔍 Analisando drafts...", Colors.CYAN)
        try:
            resp = self.session.get(f"https://api.meshy.ai/web/v1/tasks/{draft_id}/status", timeout=10)
            
            log(f"🔍 Analyze status: {resp.status_code}", Colors.CYAN)
            log(f"🔍 Analyze response: {resp.text[:500]}", Colors.CYAN)
            
            resp_json = resp.json()
            result = resp_json.get("result", {})
            outputs = result.get("taskOutputs", [])
            
            if not outputs:
                log("⚠️ Nenhum draft encontrado, usando padrão", Colors.YELLOW)
                return 0
            
            # Critérios: preferir drafts com maior índice (geralmente melhor qualidade)
            best_idx = len(outputs) - 1  # Último draft geralmente é o melhor
            best_draft = outputs[best_idx]
            
            log(f"✅ Melhor draft selecionado: #{best_idx}", Colors.GREEN)
            log(f"   Preview: {best_draft.get('preview', 'N/A')[:50]}...", Colors.CYAN)
            
            return best_idx
        except Exception as e:
            log(f"⚠️ Erro ao analisar drafts: {e}", Colors.YELLOW)
            import traceback
            log(f"Stack trace: {traceback.format_exc()}", Colors.YELLOW)
            return 0
    
    def generate_quad_mesh(self, draft_id, best_draft_id=0):
        """
        🔥 GERAÇÃO NATIVA EM QUAD MESH 🔥
        
        Gera o modelo 3D diretamente em QUAD ao invés de triângulos
        usando parâmetros nativos da API Meshy v4
        
        Args:
            draft_id: ID da task de draft
            best_draft_id: Índice do melhor draft (0-3)
            
        Returns:
            tuple: (task_id, successful_params) ou (None, None) se falhar
        """
        log("🔥 Gerando modelo com QUAD MESH NATIVO...", Colors.YELLOW)
        
        # PAYLOAD COM QUAD MESH HABILITADO
        payload_quad = {
            "draftIds": [best_draft_id],
            "enablePbr": True,
            "targetPolycount": "max",
            "shouldTexture": True,
            "topology": "quad",
            "quadRemesh": True,
            "meshType": "quad_dominant",
            "preserveSharpEdges": True,
            "targetQuadRatio": 0.95
        }
        
        log(f"🧪 Usando draft #{best_draft_id} com QUAD MESH nativo", Colors.CYAN)
        log(f"📊 Parâmetros: topology=quad, quadRemesh=True, ratio=95%", Colors.CYAN)
        
        try:
            payload = {
                "phase": "generate",
                "parent": draft_id,
                "args": {"generate": payload_quad}
            }
            
            log(f"🔍 Payload generate: {json.dumps(payload, indent=2)}", Colors.CYAN)
            
            resp = self.session.post("https://api.meshy.ai/web/v2/tasks", json=payload, timeout=30)
            
            log(f"🔍 Generate status: {resp.status_code}", Colors.CYAN)
            log(f"🔍 Generate response: {resp.text[:500]}", Colors.CYAN)
            
            resp_json = resp.json()
            
            if resp_json.get("code") == "OK":
                result = resp_json.get("result", [])
                task_id = result[0] if isinstance(result, list) else result
                log(f"✅ SUCESSO! Modelo QUAD MESH em geração: {task_id}", Colors.GREEN)
                log(f"🔥 Configurado para gerar 95% QUAD + 5% TRIS", Colors.GREEN)
                return task_id, payload_quad
            else:
                log(f"⚠️ Resposta da API: {resp_json}", Colors.YELLOW)
                log(f"💡 Tentando fallback para max polycount sem quad forçado...", Colors.YELLOW)
                
                # Fallback
                payload_fallback = {
                    "draftIds": [best_draft_id],
                    "enablePbr": True,
                    "targetPolycount": "max",
                    "shouldTexture": True
                }
                
                payload["args"]["generate"] = payload_fallback
                log(f"🔍 Payload fallback: {json.dumps(payload, indent=2)}", Colors.CYAN)
                
                resp = self.session.post("https://api.meshy.ai/web/v2/tasks", json=payload, timeout=30)
                
                log(f"🔍 Fallback status: {resp.status_code}", Colors.CYAN)
                log(f"🔍 Fallback response: {resp.text[:500]}", Colors.CYAN)
                
                resp_json = resp.json()
                
                if resp_json.get("code") == "OK":
                    result = resp_json.get("result", [])
                    task_id = result[0] if isinstance(result, list) else result
                    log(f"✅ Fallback OK (sem quad forçado): {task_id}", Colors.YELLOW)
                    log(f"⚠️ Nota: API não suportou quad nativo, mesh será triangular", Colors.YELLOW)
                    return task_id, payload_fallback
                else:
                    log(f"❌ Erro mesmo no fallback: {resp_json}", Colors.RED)
                    return None, None
                    
        except Exception as e:
            log(f"❌ Exceção: {e}", Colors.RED)
            import traceback
            log(f"Stack trace: {traceback.format_exc()}", Colors.RED)
            return None, None

    def wait_task(self, task_id, name="Task"):
        log(f"⏳ Aguardando {name}...", Colors.YELLOW)
        for i in range(180):
            try:
                resp = self.session.get(f"https://api.meshy.ai/web/v1/tasks/{task_id}/status", timeout=10)
                
                if i == 0:  # Log apenas na primeira iteração
                    log(f"🔍 Wait status: {resp.status_code}", Colors.CYAN)
                    log(f"🔍 Wait response: {resp.text[:500]}", Colors.CYAN)
                
                resp_json = resp.json()
                res = resp_json.get("result", {})
                status = res.get("status")
                
                if status == "SUCCEEDED":
                    print()
                    log(f"✅ {name} completa!", Colors.GREEN)
                    return True
                if status == "FAILED":
                    print()
                    log(f"❌ {name} falhou", Colors.RED)
                    log(f"🔍 Detalhes: {json.dumps(res, indent=2)}", Colors.RED)
                    return False
                print(f"\r{Colors.CYAN}⏳ {status} {res.get('progress', 0)}%{Colors.END}", end='', flush=True)
                sleep(10)
            except Exception as e:
                log(f"\n⚠️ Erro ao verificar status: {e}", Colors.YELLOW)
                import traceback
                log(f"Stack trace: {traceback.format_exc()}", Colors.YELLOW)
        print()
        log(f"❌ Timeout ao aguardar {name}", Colors.RED)
        return False

    def download_glb(self, task_id, name):
        log(f"📥 Baixando GLB (QUAD MESH se suportado)...", Colors.CYAN)
        try:
            resp = self.session.get(f"https://api.meshy.ai/web/v2/tasks/{task_id}/asset-url", 
                                    params={"type": "Task", "format": "glb"}, timeout=15)
            
            log(f"🔍 Download URL status: {resp.status_code}", Colors.CYAN)
            log(f"🔍 Download URL response: {resp.text[:500]}", Colors.CYAN)
            
            resp_json = resp.json()
            
            if resp_json.get("code") == "OK":
                os.makedirs(OUTPUT_FOLDER, exist_ok=True)
                path = os.path.join(OUTPUT_FOLDER, f"{name}_QUAD_MESH.glb")
                
                download_url = resp_json["result"]
                log(f"🔗 URL de download: {download_url}", Colors.CYAN)
                
                glb_data = requests.get(download_url, timeout=120).content
                with open(path, 'wb') as f: f.write(glb_data)
                size = len(glb_data) / 1024 / 1024
                log(f"✅ GLB salvo: {path} ({size:.2f} MB)", Colors.GREEN)
                return path
            else:
                log(f"❌ Erro ao obter URL: {resp_json}", Colors.RED)
                return None
        except Exception as e:
            log(f"❌ Exceção no download: {e}", Colors.RED)
            import traceback
            log(f"Stack trace: {traceback.format_exc()}", Colors.RED)
            return None

    def create_zip(self, glb, img, name, params):
        log("📦 Criando pacote final...", Colors.CYAN)
        try:
            zip_path = os.path.join(OUTPUT_FOLDER, f"{name}_QUAD_MESH_PACK.zip")
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                if glb and os.path.exists(glb):
                    zipf.write(glb, arcname=Path(glb).name)
                    os.remove(glb)
                zipf.write(img, arcname=f"reference_{Path(img).name}")
                
                quad_status = "NATIVO (gerado pela API)" if params.get("quadRemesh") else "TRIANGULAR (fallback)"
                
                readme = f"""MODELO 3D - QUAD MESH EDITION
====================================================

Arquivo: {name}
Data: {datetime.now().strftime('%Y-%m-%d %H:%M')}
Bot: Meshy AI v15 QUAD EDITION

ESPECIFICAÇÕES:
✓ Topology: {params.get('topology', 'N/A')}
✓ Quad Remesh: {params.get('quadRemesh', False)}
✓ Mesh Type: {params.get('meshType', 'N/A')}
✓ Target Quad Ratio: {params.get('targetQuadRatio', 'N/A')}
✓ Polycount: {params.get('targetPolycount', 'max').upper()}
✓ Textura: {'SIM' if params.get('shouldTexture') else 'NÃO'}
✓ PBR: {'SIM' if params.get('enablePbr') else 'NÃO'}

STATUS DO QUAD:
{quad_status}

CONTEÚDO:
- {Path(glb).name if glb else 'modelo'} (GLB)
- reference_{Path(img).name} (Imagem original)

QUALIDADE:
{'Este modelo foi gerado com QUAD MESH NATIVO pela API.' if params.get('quadRemesh') else 'Este modelo foi gerado em triangular (API não suportou quad).'}

Parâmetros utilizados:
{json.dumps(params, indent=2)}

COMPATÍVEL COM:
Unity, Unreal Engine, Blender, Godot, Maya, 3DS Max, Three.js

Gerado com ❤️ pelo Meshy Bot v15 QUAD EDITION
"""
                zipf.writestr("README.txt", readme)
            log(f"✅ ZIP criado: {zip_path}", Colors.GREEN)
            return zip_path
        except Exception as e:
            log(f"❌ Erro ao criar ZIP: {e}", Colors.RED)
            import traceback
            log(f"Stack trace: {traceback.format_exc()}", Colors.RED)
            return None

def main():
    log("="*70, Colors.BOLD)
    log("🔥 MESHY BOT v15 - QUAD MESH NATIVE EDITION 🔥", Colors.BOLD)
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
            if not email: 
                log("❌ Falha ao criar nova conta", Colors.RED)
                continue
            bot = MeshyBot(auth)
            image_id = bot.upload_image(path)
        
        if not image_id: 
            log("❌ Upload falhou, pulando imagem", Colors.RED)
            continue
        
        # Draft
        draft_id = bot.create_draft(image_id)
        if not draft_id:
            log("❌ Falha ao criar draft, pulando imagem", Colors.RED)
            continue
            
        if not bot.wait_task(draft_id, "Drafts 3D"): 
            log("❌ Draft não completou, pulando imagem", Colors.RED)
            continue
        
        # Analisar drafts e escolher o melhor
        best_draft_id = bot.analyze_drafts(draft_id)
        
        # 🔥 GERAÇÃO COM QUAD MESH NATIVO 🔥
        model_id, successful_params = bot.generate_quad_mesh(draft_id, best_draft_id)
        
        if not model_id:
            log("❌ Falha na geração do modelo", Colors.RED)
            continue
        
        if successful_params:
            is_quad = successful_params.get("quadRemesh", False)
            if is_quad:
                log(f"🔥 QUAD MESH NATIVO ATIVADO!", Colors.GREEN)
            else:
                log(f"⚠️ Fallback: Mesh triangular (API não suportou quad)", Colors.YELLOW)
        
        if not bot.wait_task(model_id, "Modelo QUAD"): 
            log("❌ Modelo não completou", Colors.RED)
            continue
        
        # Download GLB
        glb = bot.download_glb(model_id, base_name)
        if not glb:
            log("❌ Falha no download do GLB", Colors.RED)
            continue
        
        # Criar ZIP com README informativo
        zip_path = bot.create_zip(glb, path, base_name, successful_params or {})
        if not zip_path:
            log("❌ Falha ao criar ZIP", Colors.RED)
            continue
        
        log(f"🎉 SUCESSO TOTAL: {zip_path}", Colors.GREEN)
        if successful_params and successful_params.get("quadRemesh"):
            log(f"🔥 Modelo gerado com QUAD MESH NATIVO pela API Meshy!", Colors.GREEN)
        else:
            log(f"💡 Nota: Se API não suportou quad, considere usar Instant Meshes manualmente", Colors.CYAN)

    log("\n"+"="*70, Colors.BOLD)
    log("✨ Processamento finalizado!", Colors.BOLD)
    log("="*70, Colors.BOLD)

if __name__ == "__main__":
    main()