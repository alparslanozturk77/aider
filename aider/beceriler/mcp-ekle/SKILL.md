---
name: mcp-ekle
description: MCP sunucusu eklerken, yapılandırırken ya da bağlanmayan bir sunucuyu teşhis ederken kullan. "mcp ekle", "mcp sunucu", "mcp çalışmıyor", "mcp bağlanmıyor" isteklerinde tetiklenir.
---

## Yapılandırma

Proje kökünde `.mcp.json`. Biçim Claude Code ile aynıdır, mevcut dosyalar
doğrudan kopyalanabilir.

```json
{
  "mcpServers": {
    "postgres": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-postgres"],
      "env": {"DATABASE_URL": "postgres://..."},
      "cwd": "/istege/bagli/dizin"
    }
  }
}
```

`command` zorunlu; `args`, `env`, `cwd` isteğe bağlı.

`.mcp.json` `.gitignore`'dadır çünkü `env` içinde token taşıyabilir. Takımla
paylaşılacak bir şablon gerekiyorsa `ornek/mcp.json` dosyasını güncelle.

## Ekledikten sonra

`/mcp reload` sunucuları yeniden başlatır — aider'ı kapatmana gerek yok.
`/mcp` bağlı sunucuları ve her birinin araçlarını listeler.

Araçlar modele `mcp__<sunucu>__<araç>` adıyla görünür.

## Bağlanmıyorsa

Sırayla ele:

1. **Komut elle çalışıyor mu?** Bash ile aynı komutu çalıştır:
   `npx -y @modelcontextprotocol/server-postgres`
   Sunucu stdio bekler; hemen çıkıyorsa ya da hata basıyorsa sorun aider'da değil.

2. **Yol mutlak mı?** `command` göreli bir yolsa aider'ın çalışma dizinine
   göre çözülür. Mutlak yol ver ya da `cwd` ayarla.

3. **Ortam değişkenleri yerinde mi?** Sunucu `DATABASE_URL` gibi bir değişken
   bekliyorsa `env` bloğunda olmalı; kabuğundaki değişken otomatik geçmez
   (aider kendi ortamını geçirir, `env` onun üzerine yazar).

4. **JSON geçerli mi?** `python -m json.tool .mcp.json` ile doğrula.

5. **Hata mesajını oku.** Aider sunucu başlatılamazsa nedeni yazar. Bir
   sunucunun ölmesi oturumu düşürmez; diğerleri çalışmaya devam eder.

## Araç onayı

Sunucunun `readOnlyHint` verdiği araçlar onay sorulmadan çalışır. Vermeyenler
yan etkili sayılır ve izin sisteminden geçer.

Bir MCP aracını sürekli onaylıyorsan `.aider/permissions.yml` içine kural yaz:

```yaml
allow:
  - mcp__postgres__query
```

## Çevrimdışı kurumda MCP

Kurum sunucusu internete çıkamıyorsa yaygın örneklerin çoğu **çalışmaz**:

```json
{"command": "npx", "args": ["-y", "@modelcontextprotocol/server-postgres"]}
```

`npx -y` paketi çalışma anında npm'den indirir. İnternet yoksa sunucu hiç
başlamaz.

Çevrimdışı için üç seçenek, tercih sırasıyla:

**1. Python ile kendi sunucunu yaz (en sağlam).**

Yalnızca standart kütüphane kullanırsan hiçbir bağımlılık indirmen gerekmez.
Protokol küçüktür — üç metot yeter. Sunucuyu depoya koy, `.mcp.json` içinde
mutlak yolla çağır:

```json
{
  "mcpServers": {
    "satellite": {
      "command": "/usr/bin/python3",
      "args": ["/opt/kurum/mcp/satellite_server.py"],
      "env": {"SATELLITE_URL": "https://satellite.kurum.local"}
    }
  }
}
```

RHEL'de `/usr/bin/python3` her zaman vardır (3.6/3.9); sunucun yalnızca
standart kütüphane kullanıyorsa bu sürümler yeterli — aider'ın Python 3.10+
gereksinimi MCP sunucusunu bağlamaz, çünkü ayrı bir süreçtir.

**2. Node paketini önceden indirip taşı.**

İnternete çıkabilen bir makinede `npm pack` ya da `npm install --prefix`, sonra
dizini kuruma taşı ve `node /opt/kurum/mcp/.../index.js` diye çağır. `npx`
kullanma.

**3. Bağımlılıkları vendor'la.**

Python sunucusu bir kütüphaneye ihtiyaç duyuyorsa wheel'lerini önceden indir:

```bash
pip download -d wheels <paket> --platform manylinux_2_28_x86_64 \
    --python-version 3.12 --only-binary=:all:
```

### Kimlik bilgisi

Çevrimdışı kurumda MCP'nin asıl kazancı budur: Satellite ya da IdM parolasını
sunucunun kendi ortamında tut, agent'ın kabuğu onu hiç görmesin. `.mcp.json`
`.gitignore`'dadır ama yine de parolayı oraya yazmak yerine sunucunun bir
dosyadan ya da `systemd` ortamından okumasını tercih et.

## Yeni sunucu yazarken

Protokol: stdio üzerinden satır bazlı JSON-RPC 2.0. Gerekli üç metot:

- `initialize` → `protocolVersion`, `capabilities`, `serverInfo`
- `tools/list` → `{"tools": [{"name", "description", "inputSchema"}]}`
- `tools/call` → `{"content": [{"type": "text", "text": "..."}], "isError": bool}`

Çalışan bir örnek: `tests/fixtures/mcp_echo_server.py`

Sunucu **stdout'a yalnızca JSON yazmalı**; log'lar stderr'e gitmeli. Aider
JSON olmayan satırları yoksayar ama bu davranışa güvenme.
