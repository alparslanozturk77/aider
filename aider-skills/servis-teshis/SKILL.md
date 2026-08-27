---
name: servis-teshis
description: PostgreSQL, Redis, RabbitMQ, Nginx ya da Apache sorunlarını incelerken kullan. Sağlık kontrolü, bağlantı, kaynak ve yapılandırma doğrulama. "postgres", "postgresql", "psql", "redis", "rabbitmq", "nginx", "apache", "httpd", "veritabanı yavaş", "bağlanamıyor" isteklerinde tetiklenir.
---

Önce servisin ayakta olduğunu doğrula, sonra içine bak.

```bash
systemctl is-active <servis>
journalctl -u <servis> -p err -n 100 --no-pager
ss -tlnp | grep <port>        # gerçekten dinliyor mu
```

Kubernetes'te çalışıyorsa `k8s-rancher` becerisine geç; aşağıdaki komutlar
`kubectl exec` içinden de çalışır ama önce pod durumuna bakılmalı.

## PostgreSQL

Salt-okunur sağlık:

```bash
pg_isready -h localhost -p 5432
psql -c "SELECT version();"
psql -c "SELECT count(*) FROM pg_stat_activity;"
psql -c "SELECT state, count(*) FROM pg_stat_activity GROUP BY state;"
psql -c "SELECT pid, now()-query_start AS sure, state, left(query,60)
         FROM pg_stat_activity
         WHERE state <> 'idle' ORDER BY sure DESC LIMIT 10;"
psql -c "SELECT * FROM pg_stat_replication;"     # replikasyon gecikmesi
psql -c "SELECT pg_size_pretty(pg_database_size(current_database()));"
```

Neye bakılır:

- `max_connections`'a yaklaşan bağlantı sayısı → havuz tükeniyor
- `idle in transaction` durumunda uzun süre kalan oturumlar → kilit tutuyor,
  vacuum'u engelliyor
- `pg_stat_replication` içinde büyüyen `replay_lag` → replika geride
- Uzun süren sorgular → `pg_locks` ile kilit zinciri kontrol et

**Asla onaysız:** `DROP`, `DELETE`, `TRUNCATE`, `UPDATE`, `ALTER`,
`pg_terminate_backend`, `VACUUM FULL` (tabloyu kilitler).

## Redis

```bash
redis-cli ping
redis-cli info server
redis-cli info memory
redis-cli info replication
redis-cli info clients
redis-cli slowlog get 10
redis-cli --stat
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
rabbitmqctl list_connections
rabbitmqctl cluster_status
rabbitmqctl list_queues name messages_unacknowledged
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

## Nginx / Apache

Yapılandırma değiştirmeden önce **her zaman** doğrula:

```bash
nginx -t                      # sözdizimi testi
nginx -T                      # etkin yapılandırmanın tamamı
httpd -t                      # Apache
apachectl configtest
```

```bash
ss -tlnp | grep -E ':80|:443'
tail -n 200 /var/log/nginx/error.log
tail -n 200 /var/log/httpd/error_log
openssl s_client -connect localhost:443 -servername <alan> </dev/null 2>&1 | head -20
```

Neye bakılır:

- `upstream timed out` / `connect() failed` → arka uç ayakta değil, sorun web
  sunucusunda değil
- `502 Bad Gateway` → upstream çöktü ya da yanlış adres
- `504` → upstream yavaş, `proxy_read_timeout` yetmiyor
- Sertifika süresi: `openssl x509 -enddate -noout -in <cert>`
- SELinux RHEL'de sık suçludur: `ausearch -m avc -ts recent` — nginx'in
  upstream'e bağlanmasını engelleyebilir (`httpd_can_network_connect`)

**Fark önemli:** `reload` yapılandırmayı yeniden okur, bağlantıları korur.
`restart` bağlantıları keser. Üretimde `reload` tercih et ve öncesinde `-t`
ile doğrula — bozuk yapılandırmayla restart servisi tamamen düşürür.

## Raporlama

Belirtiyi sebebe bağla. "Redis bellek %94" yetmez; "Redis maxmemory'ye
yaklaştı, son saatte 40k anahtar evict edildi, cache hit oranı düştü — API
gecikmesinin sebebi bu olabilir" doğru rapordur.

Ölçmediğin şeyi söyleme. Komutu çalıştır, çıktısını göster.
