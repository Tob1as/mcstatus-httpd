# mcstatus-httpd

mcstatus-httpd shows any information of a Minecraft Server via HTTP-Server as JSON. 
It used [mcstatus](https://github.com/py-mine/mcstatus).

## INFO

This is (currently) written for my benefit only.  
You can use it, but I won't give support if it doesn't work for you. (I'm also not a Python expert!).  
But you are welcome to work on it. ;-)

## Minecraft Server

I use Minecraft Server with Docker:
* [Minecraft Java Edition](https://github.com/itzg/docker-minecraft-server)
* [Minecraft Bedrock Edition](https://github.com/itzg/docker-minecraft-bedrock-server)

Examples for docker-compose (minecraft.yml, minecraft-bedrock.yml) you can find here: [click](https://github.com/Tob1asDocker/Collection/tree/master/docker-compose_examples)

### Requirements

Minecraft (Java) must enable [Query](https://wiki.vg/Query)!

## Use

with docker-compose:  
```yml
version: '2.4'
services:

  mcstatus-httpd:
    image: ghcr.io/tob1as/mcstatus-httpd:latest
    container_name: mcstatus-httpd
    restart: unless-stopped
    ports:
      - 8080:8080/tcp
    environment:
      #TZ: Europe/Berlin
      MINECRAFT_JAVA_SERVER: minecraft.example.com
      MINECRAFT_JAVA_SERVER_PORT: 25565
      MINECRAFT_BEDROCK_SERVER: minecraft-bedrock.example.com
      MINECRAFT_BEDROCK_SERVER_PORT: 19132
    healthcheck:
      test:  wget --quiet --tries=1 --spider http://localhost:8080/healthcheck || exit 1
      interval: 120s
      timeout: 3s
      retries: 3
```

local:
* install: `pip3 install mcstatus`
* set variable/env
* start: `python3 -u ./minecraft-status.py`

## Example Output

URL: `http://localhost:8080`

```json
{
	"java": {
		"hostname": "minecraft.example.com",
		"port": 25565,
		"software": {
			"version": "1.18.1",
			"brand": "vanilla",
			"plugins": ""
		},
		"players": {
			"online": 3,
			"max": 20,
			"list": "Player1, Player2, Player3"
		},
		"map": "world",
		"motd": "A \u00a7l\u00a7cMinecraft\u00a7r \u00a7nserver"
	},
	"bedrock": {
		"hostname": "minecraft-bedrock.example.com",
		"port": 19132,
		"software": {
			"version": "1.18.11",
			"brand": "MCPE",
			"protocol": "486"
		},
		"players": {
			"online": 0,
			"max": 20
		},
		"map": "Bedrock level",
		"motd": "Minecraft Bedrock Server",
		"gamemode": "Survival"
	}
}
```
