import os
import time
import json
from mcstatus import MinecraftServer
from mcstatus import MinecraftBedrockServer
from http.server import BaseHTTPRequestHandler, HTTPServer
from http import HTTPStatus
#import ssl

MINECRAFT_SERVER = str(os.environ.get('MINECRAFT_SERVER', 'localhost'))
MINECRAFT_SERVER_PORT = int(os.environ.get('MINECRAFT_SERVER_PORT', 25565))

MINECRAFT_BEDROCK_SERVER = str(os.environ.get('MINECRAFT_BEDROCK_SERVER', MINECRAFT_SERVER))
MINECRAFT_BEDROCK_SERVER_PORT = int(os.environ.get('MINECRAFT_BEDROCK_SERVER_PORT', 19132))

HTTPD_HOST = str(os.environ.get('HTTP_HOST', '0.0.0.0'))
HTTPD_PORT = int(os.environ.get('HTTP_PORT', 8080))

print(f"load env: MINECRAFT_SERVER={MINECRAFT_SERVER}:{MINECRAFT_SERVER_PORT} ; MINECRAFT_BEDROCK_SERVER={MINECRAFT_BEDROCK_SERVER}:{MINECRAFT_BEDROCK_SERVER_PORT}")

# healthcheck
def do_healthcheck(self):
    self.send_response(HTTPStatus.OK.value) # 200
    self.send_header('Content-type','text/html')
    self.end_headers()
    
    #t = time.localtime()
    #current_time = time.strftime("%Y-%m-%d %H:%M:%S", t)
    ##print(f"healthcheck call at {current_time}.")
    
    #self.wfile.write(bytes("<html><head><title>Minecraft Status: healthcheck</title></head>", "utf-8"))
    #self.wfile.write(bytes("<body>", "utf-8"))
    #self.wfile.write(bytes(f"<b> It works !</b> <br><br>Current time: {current_time}", "utf-8"))
    ##self.wfile.write(bytes("<p>Request: %s</p>" % self.path, "utf-8"))
    #self.wfile.write(bytes("</body></html>", "utf-8"))

# mc status as json
def do_mcstatus(self):
    self.send_response(HTTPStatus.OK.value)  # 200
    self.send_header("Content-type", "application/json")
    #self.send_header('Access-Control-Allow-Origin', '*')
    self.end_headers()
    
    # mcstatus docs: https://github.com/Dinnerbone/mcstatus
    # MinecraftServer
    server = MinecraftServer.lookup(MINECRAFT_SERVER + ':' + str(MINECRAFT_SERVER_PORT))
    query = server.query()   # 'query' has to be enabled in a servers' server.properties file.
    print(f"The Minecraft Server has {query.players.online} players online, list: {', '.join(query.players.names)}")
    PLAYER_ONLINE_NAMES=(f"{', '.join(query.players.names)}")
    SOFTWARE_PLUGINS=(f"{', '.join(query.software.plugins)}")
    # MinecraftBedrockServer
    server = MinecraftBedrockServer.lookup(MINECRAFT_BEDROCK_SERVER + ':' + str(MINECRAFT_BEDROCK_SERVER_PORT))
    status = server.status()
    print(f"The Minecraft Bedrock Server has {status.players_online} players online.")

    # JSON
    jsondata = {
      'java': {
        'hostname': MINECRAFT_SERVER,
        'port': int(MINECRAFT_SERVER_PORT),
        'software': {
          'version': query.software.version,
          'brand': query.software.brand,
          'plugins': SOFTWARE_PLUGINS
        },
        'players': {
          'online': int(query.players.online),
          'max': int(query.players.max),
          'list': PLAYER_ONLINE_NAMES
        },
    	'map': query.map,
    	'motd': query.motd
      },
      'bedrock': {
        'hostname': MINECRAFT_BEDROCK_SERVER,
        'port': int(MINECRAFT_BEDROCK_SERVER_PORT),
         'software': {
          'version': status.version.version,
          'brand': status.version.brand,
          'protocol': status.version.protocol
        },
        'players': {
          'online': int(status.players_online),
          'max': int(status.players_max)
        },
        'map': status.map,
        'motd': status.motd,
        'gamemode': status.gamemode
      }
    }
    
    # httpd output
    self.wfile.write(json.dumps(jsondata).encode('utf-8'))  


class MinecraftStatusServer(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/healthcheck':
            do_healthcheck(self)
        #elif self.path == '/test':
        #    do_test(self)
        else:
            do_mcstatus(self)
      

if __name__ == "__main__":        
    httpd = HTTPServer((HTTPD_HOST, HTTPD_PORT), MinecraftStatusServer)

    # https ?
    #ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    #ctx.set_ciphers('EECDH+AESGCM:EDH+AESGCM')
    #ctx.check_hostname = False
    #ctx.load_cert_chain(certfile='ssl.crt', keyfile="ssl.key")
    #httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)

    print("Server started http://%s:%s" % (HTTPD_HOST, HTTPD_PORT))

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass

    httpd.server_close()
    print("Server stopped.")
