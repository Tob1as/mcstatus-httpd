// Random status JSON like mcstatus-httpd, new values on every request (nginx njs).
// - Java: 0-20 players (Query: full list), sometimes more than 12 (status fallback: only a
//   sample of 12 names), sometimes a Geyser player (".Name", no avatar -> name as text),
//   about every 8th request offline.
// - Bedrock: 0-10 players (no list), about every 8th request offline.

var NAMES = [
    'Notch', 'jeb_', 'Dinnerbone', 'Grumm', 'PassTheMayo', 'Technoblade', 'Dream', 'Grian',
    'MumboJumbo', 'Xisuma', 'iskall85', 'TangoTek', 'ImpulseSV', 'Etho', 'docm77', 'Keralis',
    'GeminiTay', 'Pearlescentmoon', 'Scar', 'BdoubleO100',
];

function randomInt(min, max) {
    return min + Math.floor(Math.random() * (max - min + 1));
}

function pick(list, count) {
    var copy = list.slice();
    var result = [];
    while (result.length < count && copy.length > 0) {
        result.push(copy.splice(randomInt(0, copy.length - 1), 1)[0]);
    }
    return result;
}

function java() {
    if (Math.random() < 0.125) {
        return { hostname: 'minecraft.example.com', port: 25565, online: false, error: 'Server unreachable' };
    }
    var online = randomInt(0, 20);
    var query = online <= 12;  // more than 12 players: simulate the status fallback (sample only)
    var list = pick(NAMES, Math.min(online, 12));
    if (list.length > 0 && Math.random() < 0.2) {
        list[list.length - 1] = '.BedrockSteve';  // Geyser/Floodgate player
    }
    return {
        hostname: 'minecraft.example.com',
        port: 25565,
        online: true,
        software: {
            version: '1.21.4',
            brand: query ? 'Paper on 1.21.4' : null,
            plugins: query ? ['LuckPerms 5.4.141', 'EssentialsX 2.20.1'] : [],
        },
        players: { online: online, max: 20, list: list },
        map: query ? 'world' : null,
        motd: 'Mock server\nrandom players',
    };
}

function bedrock() {
    if (Math.random() < 0.125) {
        return { hostname: 'minecraft.example.com', port: 19132, online: false, error: 'Server unreachable' };
    }
    return {
        hostname: 'minecraft.example.com',
        port: 19132,
        online: true,
        software: { version: '1.21.50', brand: 'MCPE', protocol: 766 },
        players: { online: randomInt(0, 10), max: 10 },
        map: 'Bedrock level',
        motd: 'Mock Bedrock server',
        gamemode: 'Survival',
    };
}

function status(r) {
    var data = {
        date: new Date().toISOString().replace(/\.\d+Z$/, '+00:00'),
        java: java(),
        bedrock: bedrock(),
    };
    r.headersOut['Content-Type'] = 'application/json';
    r.headersOut['Cache-Control'] = 'no-store';
    r.return(200, JSON.stringify(data));
}

export default { status };
