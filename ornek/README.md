# Yapılandırma şablonları

Bu dizin kopyalanmaya hazır örnek yapılandırmaları tutar. Gizli dizin değil:
`.gitignore`'daki `.aider*` kuralı burayı etkilemez, dolayısıyla şablonlar
depoda kalır.

| Şablon | Nereye kopyala | Ne için |
|---|---|---|
| `env` | `.env` (proje kökü) | Endpoint adresi ve API anahtarı |
| `aider.conf.yml` | `.aider.conf.yml` | Model, agent modu, izin modu |
| `aider.model.settings.yml` | `.aider.model.settings.yml` | Model davranışı: kurum + yerel modeller |
| `aider.model.metadata.json` | `.aider.model.metadata.json` | Bağlam penceresi ve maliyet |
| `permissions.yml` | `.aider/permissions.yml` | Araç izin kuralları |
| `mcp.json` | `.mcp.json` | MCP sunucuları |

Hepsini birden kurmak için:

```bash
cp ornek/env                        .env
cp ornek/aider.conf.yml             .aider.conf.yml
cp ornek/aider.model.settings.yml   .aider.model.settings.yml
cp ornek/aider.model.metadata.json  .aider.model.metadata.json
cp ornek/mcp.json                   .mcp.json
mkdir -p .aider && cp ornek/permissions.yml .aider/permissions.yml
```

`.env` ve `.mcp.json` gizli bilgi taşıyabildiği için `.gitignore`'da — kopyaladıktan
sonra kendi değerlerini girmen gerekir.

## Beceriler

Örnek beceriler şablon değil, doğrudan çalışır durumda ve programla birlikte
geliyor: `aider/beceriler/` dizininde.
Kopyalamana gerek yok, aider onları oradan okur.

- `aider-skills/` — depoya girer, takımla paylaşılır
- `.aider/skills/` — kişisel, depoya girmez, aynı adlı paylaşılan beceriyi ezer

Yeni beceri oluşturmak için oturum içinde `/skills new <ad>`.
