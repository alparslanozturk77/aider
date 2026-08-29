---
name: servis-teshis
description: PostgreSQL, Redis ya da RabbitMQ sorunlarını incelerken kullan. Sağlık kontrolü, bağlantı, kaynak ve kuyruk durumu. "postgres", "postgresql", "psql", "redis", "rabbitmq", "veritabanı yavaş", "kuyruk şişti", "bağlanamıyor" isteklerinde tetiklenir. Nginx/Apache için `web-sunucu` becerisini kullan.
---

## Adım 0 — servis konteynerde mi? (önce bunu sor)

`systemctl is-active postgresql` **inactive** derken port dinleniyorsa servis
konteynerdedir. `systemctl`e bakıp "servis kapalı" demek en sık yapılan hata.

```bash
ss -tlnp | grep <port>
```

Dinleyen süreç `conmon` ise → podman konteyneri. `docker-proxy` ise → docker.

```bash
podman ps --format "{{.Names}}\t{{.Image}}\t{{.Status}}"
podman port -a                  # hangi konteyner hangi portu yayınlıyor
podman inspect --format "{{.Name}} {{.State.Health.Status}}" <ad>
```

Konteynerse tüm komutlar `podman exec` içinden çalışır:

```bash
podman exec <ad> psql -U postgres -c "..."
podman exec <ad> redis-cli ping
podman logs --tail 200 <ad>
```

**Host'taki istemci sürümü konteynerdekiyle aynı olmayabilir.** Ölçüldü: bir
sunucuda host `psql` 16.14, konteynerde PostgreSQL 18.4. Host istemcisiyle
bağlanmak sürüm uyarısı ya da eksik özellik verir; `podman exec` kullan.

`pg_isready` host'ta "no response" diyebilir — unix soketi konteynerin içinde,
host'ta yok. Bu servisin kapalı olduğu anlamına gelmez.

Konteyner değilse normal yol:

```bash
systemctl is-active <servis>
journalctl -u <servis> -p err -n 100 --no-pager
```

Kubernetes'te çalışıyorsa `k8s-rancher` becerisine geç.

## PostgreSQL

Salt-okunur sağlık:

```bash
psql -c "SELECT version();"
psql -c "SELECT state, count(*) FROM pg_stat_activity GROUP BY state;"
psql -c "SELECT pid, now()-query_start AS sure, state, left(query,60)
         FROM pg_stat_activity
         WHERE state <> 'idle' ORDER BY sure DESC LIMIT 10;"
psql -c "SELECT * FROM pg_stat_replication;"     # replikasyon gecikmesi
psql -c "SELECT pg_size_pretty(pg_database_size(current_database()));"
```

Neye bakılır:

- `max_connections`'a yaklaşan bağlantı sayısı → havuz tükeniyor
- `idle in transaction` durumunda uzun kalan oturumlar → kilit tutuyor,
  vacuum'u engelliyor
- `pg_stat_replication` içinde büyüyen `replay_lag` → replika geride
- Uzun süren sorgular → `pg_locks` ile kilit zinciri kontrol et

**Asla onaysız:** `DROP`, `DELETE`, `TRUNCATE`, `UPDATE`, `ALTER`,
`pg_terminate_backend`, `VACUUM FULL` (tabloyu kilitler).

## Redis

```bash
redis-cli ping
redis-cli info memory
redis-cli info replication
redis-cli info clients
redis-cli slowlog get 10
redis-cli dbsize
```

Neye bakılır:

- `used_memory` / `maxmemory` oranı — doluyorsa `evicted_keys` artar
- `evicted_keys` ve `expired_keys` — beklenmedik eviction cache'i işe yaramaz
  hale getirir
- `connected_clients` — havuz sızıntısı
- `master_link_status:down` — replikasyon kopmuş
- `rdb_last_bgsave_status:err` — kalıcılık başarısız

**Asla çalıştırma:**

- `KEYS *` — tek iş parçacıklı sunucuyu bloklar, üretimde kesinti demektir.
  Yerine `SCAN` kullan.
- `FLUSHALL`, `FLUSHDB` — tüm veriyi siler
- `DEBUG SEGFAULT`, `SHUTDOWN`
- `CONFIG SET` — çalışma anında yapılandırma değiştirir

## RabbitMQ

```bash
rabbitmqctl status
rabbitmq-diagnostics check_running
rabbitmq-diagnostics check_port_connectivity
rabbitmqctl list_queues name messages consumers memory
rabbitmqctl list_queues name messages_unacknowledged
rabbitmqctl cluster_status
```

Neye bakılır:

- Büyüyen `messages` ve `consumers = 0` → tüketici düşmüş, kuyruk şişiyor
- Yüksek `messages_unacknowledged` → tüketici alıyor ama ack'lemiyor
- `cluster_status` içinde partition → **split brain**, ciddi
- Disk ya da bellek alarmı → yayıncılar bloklanır, uygulama "takılır" görünür

Alarm durumu kritiktir: RabbitMQ bellek/disk eşiğini aşınca publisher'ları
bloklar. Uygulama hata vermez, sadece bekler.

**Asla onaysız:** `purge_queue`, `delete_queue`, `stop_app`, `reset`
(`reset` düğümü kümeden çıkarır ve veriyi siler), `force_boot`.

## Raporlama

Belirtiyi sebebe bağla: "Redis bellek %94" yetmez, "maxmemory'ye yaklaştı, son
saatte 40k anahtar evict edildi — API gecikmesinin sebebi bu olabilir" doğru
rapordur. Ölçmediğin şeyi söyleme; komutu çalıştır, çıktısını göster.
