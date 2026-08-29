---
name: podman-docker
description: Konteynerleri incelerken kullan — podman ya da docker. Hangi konteyner çalışıyor, log, kaynak, port, disk, rootless/rootful ayrımı. "podman", "docker", "konteyner", "container", "compose", "imaj", "kap çöktü", "podman ps" isteklerinde tetiklenir. Kubernetes/Rancher için `k8s-rancher`.
---

Doğrulandı: AlmaLinux 10.2, podman 5.8.2 — 2026-08-29

## Önce hangisi kurulu

**RHEL / AlmaLinux / Rocky üzerinde varsayılan `podman`'dır, `docker` genelde
kurulu DEĞİLDİR.** Ölçüldü: AlmaLinux 10.2'de `podman` ve `podman-compose`
var, `docker` ve `docker-compose` yok.

```bash
command -v podman docker podman-compose docker-compose
podman --version
```

Komutlar büyük ölçüde aynı; `docker` yerine `podman` yaz. Compose için
podman'da ayrı paket: `podman-compose`. Docker'da `docker compose` (alt komut).

## Rootful mu rootless mi — bunu atlarsan yanlış sonuç alırsın

```bash
podman info --format "{{.Host.Security.Rootless}}"
```

`true` ise konteynerler kullanıcı bazlıdır: `podman ps` yalnız senin
konteynerlerini gösterir, başkasınınkini görmezsin. Bir servisi
bulamıyorsan onu çalıştıran kullanıcıyla bak.

Systemd birimlerinin yeri de buna bağlı — ölçüldü, rootful bir makinede
`systemctl --user list-units 'podman*'` **boş döndü**:

| | Birim listesi | Quadlet dosyaları |
|---|---|---|
| rootful | `systemctl list-units 'podman*'` | `/etc/containers/systemd/` |
| rootless | `systemctl --user list-units 'podman*'` | `~/.config/containers/systemd/` |

## Salt-okunur teşhis

```bash
podman ps --format "{{.Names}}\t{{.Image}}\t{{.Status}}"
podman ps -a --format "{{.Names}} {{.Status}}"     # çıkmış kaplar da
podman port -a                                     # kap → yayınlanan port
podman inspect --format "{{.Name}} {{.State.Health.Status}}" <ad>
podman logs --tail 200 <ad>
podman stats --no-stream --format "{{.Name}} {{.CPUPerc}} {{.MemUsage}}"
podman system df
```

`Status` sütunundaki `(healthy)` / `(unhealthy)` healthcheck sonucudur —
`Up` görmek yetmez, sağlık durumuna bak.

`podman stats` **`--no-stream` olmadan ekranı kilitler**; her zaman ver.

`podman system df` disk dolduğunda ilk bakılacak yerdir; `RECLAIMABLE`
sütunu geri kazanılabilir alanı gösterir. Ölçülen bir örnek: 7 imajın
2.279GB'ından 1.626GB'ı (%71) geri kazanılabilir durumdaydı.

## Servis konteynerde mi — en sık yapılan hata

`systemctl is-active <servis>` **inactive** derken port dinleniyorsa servis
konteynerdedir.

```bash
ss -tlnp | grep <port>
```

Dinleyen süreç `conmon` ise podman, `docker-proxy` ise docker. Hangi kap
olduğunu `podman port -a` ile eşleştir, ya da conmon pid'inden:

```bash
ps -o args= -p <conmon-pid> | tr ' ' '\n' | grep -A1 -- -n
```

Sonra komutları kabın içinden çalıştır:

```bash
podman exec <ad> psql -U postgres -c "..."
podman exec <ad> nginx -t
```

**Host'taki istemci sürümü kabınkiyle aynı olmayabilir.** Ölçüldü: host
`psql` 16.14, kapta PostgreSQL 18.4. Ayrıca `pg_isready` host'ta "no
response" der — unix soketi kabın içindedir. Bunların hiçbiri servisin
kapalı olduğu anlamına gelmez.

Veri servisleri için `servis-teshis`, nginx/apache için `web-sunucu`.
Kurum registry'sinden imaj çekme/gönderme ve çevrimdışı taşıma için
`nexus-registry`.

## Yan etkili — onaysız çalıştırma

```
podman rm / rmi                 kap ya da imaj siler
podman system prune             kullanılmayan volume'ları da silebilir — VERİ KAYBI
podman stop / restart           servisi keser
podman-compose down             -v ile volume'ları da siler
podman exec ... <yazan komut>   kap içinde değişiklik yapar
```

`podman system prune` disk temizliği için önerilir ama `--volumes` ya da
bazı sürümlerde varsayılan davranış adsız volume'ları siler. Önce
`podman system df` ile neyin geri kazanılacağını göster, sonra sor.

## Raporlama

Kap listesini olduğu gibi yapıştırma. Hangi kap sorunlu, neden, kanıtı ne:

```
3 kap çalışıyor, 1 sorunlu

  api    Up 2 saat (unhealthy)
    logs --tail 200: "dial tcp 10.0.3.14:5432: connect: connection refused"
    postgres kabı aynı makinede Up (healthy) — ağ ya da yapılandırma sorunu

  postgres, nginx  Up (healthy)
```
