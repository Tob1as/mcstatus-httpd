import os
import time
import json
from mcstatus import JavaServer     # mcstatus docs: https://github.com/py-mine/mcstatus
from mcstatus import BedrockServer  # mcstatus docs: https://github.com/py-mine/mcstatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from http import HTTPStatus
#import ssl

MINECRAFT_JAVA_SERVER = str(os.environ.get('MINECRAFT_JAVA_SERVER', ''))
MINECRAFT_JAVA_SERVER_PORT = int(os.environ.get('MINECRAFT_JAVA_SERVER_PORT', 25565))                                    # TCP Port
MINECRAFT_JAVA_SERVER_PORT_QUERY = int(os.environ.get('MINECRAFT_JAVA_SERVER_PORT_QUERY', MINECRAFT_JAVA_SERVER_PORT))   # UDP Port
MINECRAFT_JAVA_SERVER_OVERWRITE = str(os.environ.get('MINECRAFT_JAVA_SERVER_OVERWRITE', MINECRAFT_JAVA_SERVER))          # overwrite with DNS or something

MINECRAFT_BEDROCK_SERVER = str(os.environ.get('MINECRAFT_BEDROCK_SERVER', ''))
MINECRAFT_BEDROCK_SERVER_PORT = int(os.environ.get('MINECRAFT_BEDROCK_SERVER_PORT', 19132))                              # UDP Port
MINECRAFT_BEDROCK_SERVER_OVERWRITE = str(os.environ.get('MINECRAFT_BEDROCK_SERVER_OVERWRITE', MINECRAFT_BEDROCK_SERVER)) # overwrite with DNS or something

HTTPD_HOST = str(os.environ.get('HTTP_HOST', '0.0.0.0'))
HTTPD_PORT = int(os.environ.get('HTTP_PORT', 8080))

print(f"load env: MINECRAFT_JAVA_SERVER={MINECRAFT_JAVA_SERVER}:{MINECRAFT_JAVA_SERVER_PORT_QUERY} ; MINECRAFT_BEDROCK_SERVER={MINECRAFT_BEDROCK_SERVER}:{MINECRAFT_BEDROCK_SERVER_PORT}")

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
    self.send_header('Access-Control-Allow-Origin', '*')
    self.end_headers()
    
    # inital json
    jsondata={}
    
    if(MINECRAFT_JAVA_SERVER and not MINECRAFT_JAVA_SERVER.isspace()):
        # Minecraft Java Server
        java_server = JavaServer.lookup(MINECRAFT_JAVA_SERVER + ':' + str(MINECRAFT_JAVA_SERVER_PORT_QUERY))
        java_server_query = java_server.query()   # 'query' has to be enabled in a servers' server.properties file.
        print(f"The Minecraft Java Server has {java_server_query.players.online} players online, list: {', '.join(java_server_query.players.names)}")
        PLAYER_ONLINE_NAMES=(f"{', '.join(java_server_query.players.names)}")
        SOFTWARE_PLUGINS=(f"{', '.join(java_server_query.software.plugins)}")
        
        jsondata["java"]= {
          'hostname': MINECRAFT_JAVA_SERVER_OVERWRITE,
          'port': int(MINECRAFT_JAVA_SERVER_PORT),
          'software': {
            'version': java_server_query.software.version,
            'brand': java_server_query.software.brand,
            'plugins': SOFTWARE_PLUGINS
          },
          'players': {
            'online': int(java_server_query.players.online),
            'max': int(java_server_query.players.max),
            'list': PLAYER_ONLINE_NAMES
          },
          'map': java_server_query.map,
          'motd': java_server_query.motd
        }
        
    if(MINECRAFT_BEDROCK_SERVER and not MINECRAFT_BEDROCK_SERVER.isspace()):
        # Minecraft Bedrock Server
        bedrock_server = BedrockServer.lookup(MINECRAFT_BEDROCK_SERVER + ':' + str(MINECRAFT_BEDROCK_SERVER_PORT))
        bedrock_server_status = bedrock_server.status()
        print(f"The Minecraft Bedrock Server has {bedrock_server_status.players_online} players online.")
        
        jsondata["bedrock"]= {
          'hostname': MINECRAFT_BEDROCK_SERVER_OVERWRITE,
          'port': int(MINECRAFT_BEDROCK_SERVER_PORT),
           'software': {
            'version': bedrock_server_status.version.version,
            'brand': bedrock_server_status.version.brand,
            'protocol': bedrock_server_status.version.protocol
          },
          'players': {
            'online': int(bedrock_server_status.players_online),
            'max': int(bedrock_server_status.players_max)
          },
          'map': bedrock_server_status.map,
          'motd': bedrock_server_status.motd,
          'gamemode': bedrock_server_status.gamemode
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
