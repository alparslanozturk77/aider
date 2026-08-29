---
name: k8s-rancher
description: Kubernetes ve Rancher üzerinde sorun ararken kullan — pod, deployment, node, namespace, log, event. Az sayıda sunucudaki docker/docker-compose için de geçerli. "kubernetes", "k8s", "rancher", "pod", "kubectl", "deployment", "node", "container", "docker" isteklerinde tetiklenir.
---

## Önce hangi kümedesin

En pahalı hata yanlış kümede komut çalıştırmaktır. Rancher'da birden çok
downstream küme aynı kubeconfig içinde olur.

```bash
kubectl config current-context
kubectl config get-contexts
```

Bağlamı **doğrulamadan** hiçbir şey yapma. Kullanıcı küme adı söylemediyse
sor; tahmin etme.

Namespace de aynı şekilde: `-n <ad>` vermezsen `default` kullanılır ve
aradığın şey orada olmayabilir. Bilmiyorsan `-A` ile tüm namespace'lere bak.

## Salt-okunur teşhis

Bu komutlar hiçbir şeyi değiştirmez, serbestçe kullan:

```bash
kubectl get pods -A                      # genel tablo
kubectl get pods -n <ns> -o wide         # hangi node'da
kubectl get deploy,sts,ds -n <ns>
kubectl get nodes -o wide
kubectl describe pod <pod> -n <ns>       # en bilgilendirici tek komut
kubectl logs <pod> -n <ns> --tail=200
kubectl logs <pod> -n <ns> --previous    # çökmeden önceki kap
kubectl get events -n <ns> --sort-by=.lastTimestamp
kubectl top nodes ; kubectl top pods -n <ns>
```

`kubectl get events --sort-by=.lastTimestamp` en çok atlanan ve en çok işe
yarayan komuttur. Pod açıklanamayan bir durumdaysa önce olaylara bak.

Log alırken `--tail` **her zaman** ver. Sınırsız log bağlamı doldurur.

## Pod durumlarını okuma

| Durum | Anlamı | Nereye bak |
|---|---|---|
| `CrashLoopBackOff` | Kap başlıyor ve çöküyor | `logs --previous` — çıkış sebebi orada |
| `ImagePullBackOff` / `ErrImagePull` | İmaj çekilemiyor | Registry erişimi, imaj adı, `imagePullSecrets` |
| `Pending` | Zamanlanamıyor | `describe` → Events; kaynak yetmiyor, taint, PVC bağlanmamış |
| `OOMKilled` | Bellek limitini aştı | `describe` → Last State; limit artır ya da sızıntı ara |
| `Evicted` | Node kaynağı bitti | Node'da disk/bellek baskısı |
| `ContainerCreating` uzun sürüyor | Volume ya da ağ | Events; PVC, CNI |
| `Terminating` takıldı | Finalizer ya da graceful shutdown | `describe`; zorlamadan önce sebebi anla |

`Running` görmek yeterli değil — `READY` sütununa bak. `1/2` demek bir kabın
hazır olmadığı demektir; readiness probe başarısız olabilir.

## Rancher'a özgü

- Rancher **projeleri** namespace gruplarıdır; `kubectl` projeyi bilmez,
  namespace ile çalışır.
- Downstream kümeye Rancher proxy'si üzerinden bağlanılır; bağlantı koparsa
  sorun kümede değil Rancher'da olabilir.
- `cattle-system` namespace'i Rancher ajanlarını barındırır
  (`cattle-cluster-agent`, `cattle-node-agent`). Küme "unavailable"
  görünüyorsa bu podların loglarına bak.
- Rancher CLI (`rancher`) kurulumdan kuruluma değişir. Kullanacaksan önce
  `rancher --help` çıktısını oku, ezberden komut yazma.

## Yan etkili komutlar — onaysız çalıştırma

```
kubectl delete ...            kaynağı siler
kubectl drain <node>          node'u boşaltır, podları taşır
kubectl cordon <node>         yeni pod almaz
kubectl scale --replicas=0    servisi durdurur
kubectl apply / patch / edit  yapılandırmayı değiştirir
kubectl rollout restart       tüm podları yeniden başlatır
kubectl exec ... -- <komut>   kap içinde komut çalıştırır
```

`kubectl delete pod` çoğu zaman "zararsız" sanılır — deployment onu yeniden
oluşturur. Ama StatefulSet'te veri kaybına, tek replikalı serviste kesintiye
yol açar. Silmeden önce ne tarafından yönetildiğine bak.

Bir şeyi değiştirmen istendiğinde önce `--dry-run=server` ile göster:

```bash
kubectl apply -f x.yaml --dry-run=server
kubectl diff -f x.yaml
```

## Podman ve Docker

**RHEL / AlmaLinux / Rocky üzerinde varsayılan `podman`'dır, `docker` genelde
kurulu DEĞİLDİR** (doğrulandı: AlmaLinux 10.2'de podman var, docker yok).
Önce hangisinin olduğuna bak:

```bash
command -v podman docker
```

Komutlar büyük ölçüde aynı; `docker` yerine `podman` yaz:

```bash
podman ps -a                       # çıkmış kaplar da görünür
podman logs --tail 200 <kap>
podman inspect <kap>
podman stats --no-stream
podman system df                   # imaj/volume disk kullanımı
podman-compose ps                  # compose ayrı paket
```

Docker varsa aynı komutlar `docker` önekiyle, compose için `docker compose`.

Podman'a özgü iki not: kapsayıcılar kök olmadan (rootless) çalışabilir, o
zaman `podman ps` kullanıcı bazlıdır — başka kullanıcının kapsayıcısını
görmezsin. Ve `systemctl --user` altında Quadlet birimleri olabilir:

```bash
systemctl --user list-units 'podman*'
```

Yan etkili: `podman rm`, `podman rmi`, `podman system prune` (bu sonuncusu
kullanılmayan volume'ları da silebilir — veri kaybı riski), `podman-compose
down` (`-v` ile volume'ları da siler). Docker karşılıkları aynı.

## Raporlama

Pod tablosunu olduğu gibi yapıştırma. Sorunlu olanları ayır:

```
üretim namespace'inde 34 pod, 2 sorunlu

  api-7d9f-x2k    CrashLoopBackOff   12 restart
    logs --previous: "connection refused: postgres:5432"
  worker-5b8-mn4  Pending
    events: "0/6 nodes available: insufficient memory"

diğer 32 pod Running ve Ready
```

Çıkarım yap, sadece durum listeleme. "Neden" sorusuna cevap ver.
