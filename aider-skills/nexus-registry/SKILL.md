---
name: nexus-registry
description: Kurum içi konteyner registry'si (Nexus) ile çalışırken kullan. Login, sertifika, hosted repodan pull/push, çevrimdışı taşıma için save/load, digest doğrulama. "nexus", "registry", "imaj çek", "podman pull", "podman push", "podman save", "imaj taşı", "hosted repo" isteklerinde tetiklenir.
---

Doğrulandı: podman 5.8.2, AlmaLinux 10.2 — 2026-08-29

Kurum içi registry adresi ortama göre değişir; aşağıda `<registry>` yazan yere
kurumun adresini koy. Adresi bilmiyorsan **uydurma** — kullanıcıya sor ya da
`/etc/containers/registries.conf.d/` altındaki dosyalara bak.

## 1. Kimlik doğrulama ve sertifika

```bash
podman login <registry>
podman login --authfile /tmp/auth.json <registry>     # ayrı dosyaya yaz
```

Anahtar dosyasının yeri `REGISTRY_AUTH_FILE` ile değiştirilebilir. Otomasyonda
kullanıcının kalıcı oturumunu kirletmemek için ayrı `--authfile` tercih et.

Kurum registry'si kurumsal CA ile imzalıysa sertifikayı **yerine koy**:

```
/etc/containers/certs.d/<registry>/ca.crt
```

ya da komut başına `--cert-dir <dizin>`.

**`--tls-verify=false` kullanma.** Çalışır ama sertifika doğrulamasını kapatır;
banka ortamında denetime takılır ve ortadaki adam saldırısına açar. Sertifika
hatası alıyorsan çözüm CA'yı yerleştirmektir, doğrulamayı kapatmak değil.

## 2. Hosted repodan çekme ve gönderme

**Her zaman tam ad yaz.** Kısa ad (`alpine`) `registries.conf.d` altındaki
short-name tablosuna düşer ve beklemediğin registry'den çeker.

```bash
podman pull <registry>/<repo>/<imaj>:<etiket>
podman tag  <kaynak-imaj> <registry>/<repo>/<imaj>:<etiket>
podman push --digestfile /tmp/digest.txt <registry>/<repo>/<imaj>:<etiket>
```

`--digestfile` gönderilen imajın digest'ini dosyaya yazar — taşıma kaydı
tutmak için en temiz yol.

## 3. Çevrimdışı taşıma: save / load

İnternete çıkamayan ortama imaj taşımanın yolu. Twistlock gibi ürünlerin
imajları böyle geliyor.

```bash
podman save -o imaj.tar <imaj>:<etiket>                    # docker-archive
podman save --format oci-archive -o imaj.tar <imaj>:<etiket>
podman load -i imaj.tar
```

Varsayılan biçim `docker-archive`. **`oci-archive` belirgin ölçüde küçük** —
ölçüldü, `alpine:3.21` için 7.8 MB yerine 3.7 MB. Ağ ya da taşınabilir disk
üzerinden taşıyorsan `--format oci-archive` kullan.

`podman load` çıktısı yüklenen imajın tam adını basar; onu oku ve bir sonraki
adımda o adı kullan:

```
Loaded image: docker.io/library/alpine:3.21
```

Yükledikten sonra kurum registry'sine koymak için `tag` + `push` (bkz. 2).

Diskte yer kontrolü: imaj arşivi katmanların açılmış hâli kadar yer kaplar,
`podman load` sonrası bir o kadarı daha depoda birikir. Önce `df -h` ve
`podman system df`.

## 4. Digest tuzağı — tek bir digest yoktur

Bir imaj birden çok digest taşır (manifest listesi ve platforma özgü manifest).
Ölçüldü, hiç taşınmamış bir imajda bile ikisi farklı:

```
podman images --format "{{.Digest}}" nginx:1.29.8            -> sha256:1881968a...
podman image inspect --format "{{.Digest}}" nginx:1.29.8     -> sha256:ab15d428...
```

Bu yüzden "digest tutmuyor" demeden önce hangi digest'e baktığını netleştir:

```bash
podman image inspect --format "{{.RepoDigests}}" <imaj>
```

Kaynak ile hedefi karşılaştırırken aynı komutun çıktısını karşılaştır.

## 5. Nexus sunucusunun kendisi

**Nexus'a erişimim yok; komut referansı yazmıyorum.** Nexus tarafında bir şey
gerekirse keşifle ilerle:

- Hangi repo tipi? Nexus'ta `docker (hosted)`, `docker (proxy)` ve
  `docker (group)` farklı davranır — push yalnız *hosted*'a yapılır.
- Repo listesi ve tipleri web arayüzünde Repositories bölümünde; REST API de
  var ama sürüme göre yol değişir, önce `--help` yerine kurumun kendi
  belgesine ya da arayüze bak.
- Registry portu Nexus'un HTTP portundan farklı olabilir (repo başına
  connector). `podman login` hangi porta yapılacağını kullanıcıya sor.

## 6. Yan etkili — onaysız çalıştırma

```
podman push          registry'ye imaj yazar, etiketin üstüne yazabilir
podman rmi           yerel imajı siler
podman system prune  kullanılmayanları siler — VERİ KAYBI
podman login         kimlik bilgisi diske yazar
```

Var olan bir etiketin üstüne push etmek geri alınamaz. Push etmeden önce
hedefte o etiket var mı kontrol et ve kullanıcıya sor.
