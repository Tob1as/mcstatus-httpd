#!/usr/bin/env python
#-*- coding: utf-8 -*-

"""
mcstatus-httpd 
https://github.com/Tob1as/mcstatus-httpd

mcstatus-httpd shows any information of a Minecraft Server via HTTP-Server as JSON.
It used https://github.com/py-mine/mcstatus
"""

import os
import sys
import logging
import time
import json
from mcstatus import JavaServer     # mcstatus docs: https://github.com/py-mine/mcstatus
from mcstatus import BedrockServer  # mcstatus docs: https://github.com/py-mine/mcstatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from http import HTTPStatus
import ssl

# Variables
LOGLEVEL = str(os.environ.get('LOGLEVEL', 'INFO').upper())

MINECRAFT_JAVA_SERVER = str(os.environ.get('MINECRAFT_JAVA_SERVER', ''))
MINECRAFT_JAVA_SERVER_PORT = int(os.environ.get('MINECRAFT_JAVA_SERVER_PORT', 25565))                                    # TCP Port
MINECRAFT_JAVA_SERVER_PORT_QUERY = int(os.environ.get('MINECRAFT_JAVA_SERVER_PORT_QUERY', MINECRAFT_JAVA_SERVER_PORT))   # UDP Port
MINECRAFT_JAVA_SERVER_OVERWRITE = str(os.environ.get('MINECRAFT_JAVA_SERVER_OVERWRITE', MINECRAFT_JAVA_SERVER))          # overwrite with DNS or something

MINECRAFT_BEDROCK_SERVER = str(os.environ.get('MINECRAFT_BEDROCK_SERVER', ''))
MINECRAFT_BEDROCK_SERVER_PORT = int(os.environ.get('MINECRAFT_BEDROCK_SERVER_PORT', 19132))                              # UDP Port
MINECRAFT_BEDROCK_SERVER_OVERWRITE = str(os.environ.get('MINECRAFT_BEDROCK_SERVER_OVERWRITE', MINECRAFT_BEDROCK_SERVER)) # overwrite with DNS or something

HTTPD_HOST = str(os.environ.get('HTTP_HOST', '0.0.0.0'))
HTTPD_PORT = int(os.environ.get('HTTP_PORT', 8080))
HTTPD_SSL_ENABLE = int(os.environ.get('HTTPD_SSL_ENABLE', 0))

# Logging
logging.root.handlers = []
logging.basicConfig(format='%(asctime)s %(name)-12s %(levelname)s: %(message)s', datefmt='%Y-%m-%d %H:%M:%S', encoding='utf-8', stream=sys.stdout, level=LOGLEVEL)
logger = logging.getLogger(__name__)

logger.info(f"LOAD ENV: HTTPD_HOST={HTTPD_HOST} ; HTTPD_PORT={HTTPD_PORT} ; HTTPD_SSL_ENABLE={HTTPD_SSL_ENABLE}")
logger.info(f"LOAD ENV: MINECRAFT_JAVA_SERVER={MINECRAFT_JAVA_SERVER}:{MINECRAFT_JAVA_SERVER_PORT_QUERY} ; MINECRAFT_BEDROCK_SERVER={MINECRAFT_BEDROCK_SERVER}:{MINECRAFT_BEDROCK_SERVER_PORT}")

# current time
def currenttime():
    t = time.localtime()
    current_time = time.strftime("%Y-%m-%d %H:%M:%S", t)
    return current_time

# healthcheck
def do_healthcheck(self):
    self.send_response(HTTPStatus.OK.value) # 200
    self.send_header('Content-type','text/plain')
    self.end_headers()
    #self.wfile.write(bytes("It Works!", "utf-8"))

# mc status as json
def do_mcstatus(self):
    self.send_response(HTTPStatus.OK.value)  # 200
    self.send_header("Content-type", "application/json")
    self.send_header('Access-Control-Allow-Origin', '*')
    self.end_headers()
    
    # inital json
    jsondata={
      'date': currenttime()
    }
    
    if(MINECRAFT_JAVA_SERVER and not MINECRAFT_JAVA_SERVER.isspace()):
        # Minecraft Java Server
        java_server = JavaServer.lookup(MINECRAFT_JAVA_SERVER + ':' + str(MINECRAFT_JAVA_SERVER_PORT_QUERY))
        java_server_query = java_server.query()   # 'query' has to be enabled in a servers' server.properties file.
        logger.info(f"The Minecraft Java Server has {java_server_query.players.online} players online, list: {', '.join(java_server_query.players.list)}")
        PLAYER_ONLINE_NAMES=(f"{', '.join(java_server_query.players.list)}")
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
          'map': java_server_query.map_name,
          'motd': java_server_query.motd.raw
        }
        
    if(MINECRAFT_BEDROCK_SERVER and not MINECRAFT_BEDROCK_SERVER.isspace()):
        # Minecraft Bedrock Server
        bedrock_server = BedrockServer.lookup(MINECRAFT_BEDROCK_SERVER + ':' + str(MINECRAFT_BEDROCK_SERVER_PORT))
        bedrock_server_status = bedrock_server.status()
        logger.info(f"The Minecraft Bedrock Server has {bedrock_server_status.players.online} players online.")
        
        jsondata["bedrock"]= {
          'hostname': MINECRAFT_BEDROCK_SERVER_OVERWRITE,
          'port': int(MINECRAFT_BEDROCK_SERVER_PORT),
           'software': {
            'version': bedrock_server_status.version.name,
            'brand': bedrock_server_status.version.brand,
            'protocol': bedrock_server_status.version.protocol
          },
          'players': {
            'online': int(bedrock_server_status.players.online),
            'max': int(bedrock_server_status.players.max)
          },
          'map': bedrock_server_status.map_name,
          'motd': bedrock_server_status.motd.raw,
          'gamemode': bedrock_server_status.gamemode
        }
    
    # httpd output
    self.wfile.write(json.dumps(jsondata).encode('utf-8'))  


class MinecraftStatusServer(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/healthcheck':
            do_healthcheck(self)
        else:
            do_mcstatus(self)
      

if __name__ == "__main__":        
    httpd = HTTPServer((HTTPD_HOST, HTTPD_PORT), MinecraftStatusServer)

    # https/ssl
    if HTTPD_SSL_ENABLE and HTTPD_SSL_ENABLE == 1 and os.path.exists('ssl.crt') and os.path.exists('ssl.key'):
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.set_ciphers('EECDH+AESGCM:EDH+AESGCM')
        ctx.check_hostname = False
        ctx.load_cert_chain(certfile='ssl.crt', keyfile='ssl.key')
        httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
        HTTPD_SCHEME="https"
    else:
        HTTPD_SCHEME="http"

    logger.info("Server started %s://%s:%s" % (HTTPD_SCHEME, HTTPD_HOST, HTTPD_PORT))

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass

    httpd.server_close()
    logger.info("Server stopped.")
