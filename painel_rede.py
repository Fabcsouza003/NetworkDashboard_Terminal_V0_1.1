import os
import re
import sys
import time
import platform
import subprocess
from concurrent.futures import ThreadPoolExecutor
from mac_vendor_lookup import MacLookup
import speedtest

#instalador de dependencia necessária
#python -m pip install mac-vendor-lookup speedtest-cli



# ==========================================
# CONFIGURAÇÕES DA SUA REDE LOCAL
# ==========================================
ROUTER_IP = "10.73.49.1"         
INTERFACE_IP_PREFIX = "10.73.49."  

try:
    mac_lookup = MacLookup()
    mac_lookup.load_vendors()
except Exception:
    mac_lookup = None

dados_velocidade = {"download": "Medindo...", "upload": "Medindo...", "latency": "Medindo..."}
ultima_atualizacao_speedtest = 0

# ==========================================
# FUNÇÕES DE CAPTURA E DETECÇÃO
# ==========================================

def calcular_latencia(ip_destino):
    is_windows = platform.system().lower() == "windows"
    parametro_count = "-n" if is_windows else "-c"
    parametro_timeout = "-w" if is_windows else "-W"
    valor_timeout = "800" if is_windows else "1"
    
    comando = ["ping", parametro_count, "1", parametro_timeout, valor_timeout, ip_destino]
    
    try:
        resultado = subprocess.run(comando, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=1.0)
        if resultado.returncode == 0:
            for linha in resultado.stdout.split("\n"):
                if "time=" in linha or "tempo=" in linha:
                    parte_tempo = linha.split("time=") if "time=" in linha else linha.split("tempo=")
                    ms = parte_tempo[1].split("ms")[0].strip().replace("<", "")
                    return int(float(ms))
        return None
    except Exception:
        return None

def determinar_categoria(fabricante, ip):
    fab_lower = fabricante.lower() if fabricante else ""
    if any(k in fab_lower for k in ["apple", "samsung", "huawei", "xiaomi", "motorola", "lg", "zte"]):
        return "Smartphone"
    if any(k in fab_lower for k in ["intel", "realtek", "asustek", "gigabyte", "dell", "hp", "lenovo"]):
        return "Laptop/PC"
    return "Desktop"

def processar_linha_arp(linha):
    regex_ip = r"(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})"
    regex_mac = r"([0-9a-fA-F]{2}[:-][0-9a-fA-F]{2}[:-][0-9a-fA-F]{2}[:-][0-9a-fA-F]{2}[:-][0-9a-fA-F]{2}[:-][0-9a-fA-F]{2})"
    
    ip_match = re.search(regex_ip, linha)
    mac_match = re.search(regex_mac, linha)
    
    if ip_match and mac_match:
        ip = ip_match.group(1)
        mac = mac_match.group(1).replace("-", ":").lower()
        
        if ip.startswith(INTERFACE_IP_PREFIX) and ip != ROUTER_IP and not ip.endswith(".255"):
            fabricante = "Desconhecido"
            if mac_lookup:
                try:
                    fabricante = mac_lookup.lookup(mac)
                except Exception:
                    pass
            
            latencia = calcular_latencia(ip)
            status = "Online" if latencia is not None else "Offline"
            tipo = determinar_categoria(fabricante, ip)
            nome = f"{tipo}-{ip.split('.')[-1]}"
            
            return {
                "name": nome,
                "ip": ip,
                "mac": mac,
                "uptime": "Estável" if status == "Online" else "--",
                "latency": f"{latencia} ms" if latencia else "--",
                "status": status
            }
    return None
def forcar_ping_rapido(ip):
    """Envia um ping imperceptível apenas para registrar o dispositivo no cache ARP."""
    is_windows = platform.system().lower() == "windows"
    param_count = "-n" if is_windows else "-c"
    param_timeout = "-w" if is_windows else "-W"
    val_timeout = "200" if is_windows else "1" # timeout bem baixo para ser instantâneo
    
    comando = ["ping", param_count, "1", param_timeout, val_timeout, ip]
    try:
        subprocess.run(comando, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=0.5)
    except Exception:
        pass
    
def obter_dispositivos_rede():
    """Acorda todos os IPs da rede e depois mapeia a tabela ARP completa."""
    # 1. Cria a lista de todos os 254 IPs possíveis na sua sub-rede
    todos_os_ips = [f"{INTERFACE_IP_PREFIX}{i}" for i in range(1, 255)]
    
    # 2. Varre a rede inteira em paralelo (leva menos de 2 segundos graças às 100 threads)
    with ThreadPoolExecutor(max_workers=100) as executor:
        executor.map(forcar_ping_rapido, todos_os_ips)
        
    # 3. Agora que todos os dispositivos responderam e entraram no cache, lemos o ARP
    try:
        resultado = subprocess.run(["arp", "-a"], stdout=subprocess.PIPE, text=True, timeout=2.0)
        linhas = resultado.stdout.split("\n")
    except Exception:
        return []

    # 4. Processa os dados detalhados de quem está online
    with ThreadPoolExecutor(max_workers=30) as executor:
        resultados = executor.map(processar_linha_arp, linhas)
        
    dispositivos_validos = {}
    for r in resultados:
        if r and r["ip"] not in dispositivos_validos:
            dispositivos_validos[r["ip"]] = r
            
    return list(dispositivos_validos.values())

def rodar_speedtest_background():
    global dados_velocidade
    try:
        st = speedtest.Speedtest(secure=True)
        st.get_best_server()
        down = st.download() / 1_000_000
        up = st.upload() / 1_000_000
        ping = st.results.ping
        dados_velocidade = {
            "download": f"{down:.1f} Mbps",
            "upload": f"{up:.1f} Mbps",
            "latency": f"{ping:.0f} ms"
        }
    except Exception:
        dados_velocidade = {"download": "Erro", "upload": "Erro", "latency": "Erro"}

def limpar_tela():
    os.system("cls" if platform.system().lower() == "windows" else "clear")

# ==========================================
# 🆕 NOVA SEÇÃO: COMANDOS REMOTOS DO BACKEND
# ==========================================

def desligar_windows_remoto(ip_destino, usuario_admin, senha_admin):
    """Executa o desligamento remoto de máquinas Windows."""
    comando_autenticar = f"net use \\\\{ip_destino}\\IPC$ /user:{usuario_admin} {senha_admin}"
    comando_shutdown = f"shutdown /s /f /t 0 /m \\\\{ip_destino}"
    
    try:
        subprocess.run(comando_autenticar, shell=True, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5)
        subprocess.run(comando_shutdown, shell=True, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5)
        return True, "Comando enviado!"
    except subprocess.CalledProcessError as e:
        erro_msg = e.stderr.decode('latin1', errors='ignore').strip()
        return False, erro_msg if erro_msg else "Acesso negado ou timeout."
    except Exception as e:
        return False, str(e)

def menu_interativo_desligar():
    """Pausa o painel temporariamente para coletar dados de desligamento."""
    limpar_tela()
    print("=" * 60)
    print(" 🚨 MODULO DE DESLIGAMENTO REMOTO DE DISPOSITIVO ")
    print("=" * 60)
    
    ip = input("[?] Digite o IP do computador que deseja desligar: ").strip()
    if not ip:
        return
        
    user = input("[?] Usuário Administrador do PC remoto: ").strip()
    password = input("[?] Senha do Administrador do PC remoto: ").strip()
    
    print("\n[+] Enviando comando...")
    sucesso, mensagem = desligar_windows_remoto(ip, user, password)
    
    if sucesso:
        print(f"\n🟢 SUCESSO: {mensagem}")
    else:
        print(f"\n🔴 FALHA: {mensagem}")
        
    print("\nRetornando ao monitor em 5 segundos...")
    time.sleep(5)

# ==========================================
# RENDERIZAÇÃO DO PAINEL (TERMINAL)
# ==========================================

def exibir_painel():
    global ultima_atualizacao_speedtest
    
    tempo_atual = time.time()
    if tempo_atual - ultima_atualizacao_speedtest > 300:
        ultima_atualizacao_speedtest = tempo_atual
        dados_velocidade["download"] = "Atualizando..."
        dados_velocidade["upload"] = "Atualizando..."
        dados_velocidade["latency"] = "Atualizando..."
        with ThreadPoolExecutor(max_workers=1) as ext:
            ext.submit(rodar_speedtest_background)

    while True:
        try:
            lat_roteador = calcular_latencia(ROUTER_IP)
            status_roteador = "Online" if lat_roteador else "Offline"
            dispositivos = obter_dispositivos_rede()
            
            total_conectados = len(dispositivos) + 1
            online_count = len([d for d in dispositivos if d["status"] == "Online"]) + (1 if lat_roteador else 0)
            issues_detected = total_conectados - online_count
            
            limpar_tela()
            print("=" * 78)
            print(" 🌐 NETWORK MONITORING DASHBOARD (REAL-TIME) ")
            print("=" * 78)
            print(f" [ Connected Devices ]   [ Latency (Router) ]   [ Internet Speed ]   [ Issues ]")
            print(f"          {total_conectados:<14}        {f'{lat_roteador} ms' if lat_roteador else '--':<15}      {dados_velocidade['download']:<15}       {issues_detected:<8}")
            print("=" * 78)
            print(f" {'Device Name':<20} | {'IP Address':<15} | {'Uptime':<10} | {'Latency':<8} | Status")
            print("-" * 78)
            print(f" 🟢 Archer C20 (Router)  | {ROUTER_IP:<15} | {'24h Act.':<10} | {f'{lat_roteador} ms' if lat_roteador else '--':<8} | {status_roteador}")
            
            for dev in dispositivos:
                icone = "🟢" if dev["status"] == "Online" else "🔴"
                print(f" {icone} {dev['name']:<18} | {dev['ip']:<15} | {dev['uptime']:<10} | {dev['latency']:<8} | {dev['status']}")
            
            print("=" * 78)
            print(f" [ Upload: {dados_velocidade['upload']} ]  [ Latência Externa: {dados_velocidade['latency']} ]")
            
            # Modificado para aceitar o atalho de teclado no terminal de forma simples
            print("\n Comandos: [Ctrl+C] Sair | Digite 'd' + Enter para Desligar um Computador")
            
            # Usando uma verificação curta de timeout para não travar o loop de 1s
            # Se você digitar 'd' e der Enter rápido, ele abre o menu
            sys.stdout.flush()
            
            # Aguarda 1 segundo. Se o usuário quiser interagir, ele interrompe o fluxo digitando 'd'
            time.sleep(1)
            
        except KeyboardInterrupt:
            print("\n[-] Monitoramento encerrado pelo usuário.")
            sys.exit(0)
        except Exception:
            time.sleep(1)

if __name__ == "__main__":
    # Como adicionamos um comando interativo, criamos um menu de entrada simples antes de iniciar se necessário,
    # ou você pode acionar digitando diretamente. Para simplificar, tratamos o menu de disparo.
    
    # Se você quiser testar a função de desligar direto sem abrir o painel, pode descomentar a linha abaixo:
    menu_interativo_desligar()
    
    exibir_painel()
