---
name: guvenlik-incelemesi
description: Kodda güvenlik açığı ararken kullan. Enjeksiyon, kimlik bilgisi sızıntısı, yetki atlatma ve güvensiz varsayılanları sistematik tarar. "güvenlik", "security", "açık var mı", "zafiyet", "sızıntı" isteklerinde tetiklenir.
---

Güvenlik incelemesi yaparken sırayla şu sınıflara bak. Her sınıfta önce
**girdinin nereden geldiğini** izle: kullanıcıdan, ağdan ya da dosyadan gelen
her veri güvenilmezdir.

## 1. Enjeksiyon

Güvenilmez verinin bir yorumlayıcıya karıştığı yerler:

- **SQL** — string birleştirme ya da f-string ile sorgu kuruluyor mu?
  Parametreli sorgu kullanılmalı. Grep: `execute(`, `f"SELECT`, `+ query`
- **Kabuk** — `shell=True`, `os.system`, `eval`, `exec`. Kullanıcı verisi
  komuta giriyorsa argüman listesi kullanılmalı, string değil.
- **Yol** — `../` ile dizin dışına çıkılabiliyor mu? Yol birleştirmeden sonra
  sonucun beklenen kökün altında kaldığı doğrulanıyor mu?
- **Şablon/HTML** — kaçışsız çıktı, `|safe`, `dangerouslySetInnerHTML`

## 2. Kimlik bilgisi

- Koda gömülü anahtar, token, parola. Grep: `api_key`, `secret`, `token`,
  `password`, `sk-`, `Bearer `
- Log'a ya da hata mesajına sızan gizli bilgi
- Depoya girmiş `.env` benzeri dosyalar — `git ls-tree -r HEAD --name-only`
  ile gerçekten izlenip izlenmediğini doğrula

## 3. Yetkilendirme

- Her uç noktada kimlik **ve** yetki ayrı ayrı kontrol ediliyor mu?
- Nesne kimliği doğrudan istekten alınıyorsa, o nesnenin çağırana ait olduğu
  doğrulanıyor mu?
- Yönetici yolları yalnızca istemci tarafında mı gizleniyor?

## 4. Güvensiz varsayılanlar

- Sertifika doğrulaması kapalı: `verify=False`, `rejectUnauthorized: false`
- Zayıf kripto: MD5/SHA1 parola için, sabit IV, `random` (kripto için
  `secrets` kullanılmalı)
- Aşırı geniş CORS, `debug=True`, açık dizin listeleme

## Raporlama

Her bulgu için üç şey yaz:

1. `dosya:satır`
2. Saldırganın ne yapabileceği — somut senaryo
3. Düzeltmenin ne olduğu

Somut senaryo yazamıyorsan bulgu değildir, bildirme. Ciddiyet sırasına diz.

**Kavram kanıtı üretme.** Sorunun sınıfını ve düzeltmeyi anlat; çalışan
istismar kodu yazma.
