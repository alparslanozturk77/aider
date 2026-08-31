---
name: k8s-rancher
description: Kubernetes ve Rancher üzerinde sorun ararken kullan — pod, deployment, node, namespace, log, event. "kubernetes", "k8s", "rancher", "pod", "kubectl", "deployment", "node", "namespace" isteklerinde tetiklenir. Küme dışı tek makinedeki konteynerler için `podman-docker`.
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

Hiçbiri bir şeyi değiştirmez:

```bash
kubectl get pods -A                      # genel tablo
kubectl get pods -n <ns> -o wide         # hangi node'da
kubectl get deploy,sts,ds -n <ns>
kubectl get nodes -o wide
kubectl describe pod <pod> -n <ns>       # en bilgilendirici tek komut
kubectl logs <pod> -n <ns> --tail=200
kubectl logs <pod> -n <ns> --previous    # çökmeden önceki kap
kubectl events -n <ns>                   # zamana göre sıralı
kubectl top nodes ; kubectl top pods -n <ns>   # metrics-server gerekir
```

Olaylar en çok atlanan ve en çok işe yarayan yerdir; pod açıklanamayan bir
durumdaysa önce oraya bak. `kubectl events` ayrı bir alt komuttur (istemci
v1.36.1'de var), zamana göre sıralar, `--for pod/<ad>` ile daraltılır. Eski
`get events --sort-by=.lastTimestamp` da çalışır ama `events.k8s.io/v1` ile
üretilen olaylarda o alan boş kalıp sıralamayı yanıltabilir.

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
- Rancher CLI (`rancher`) kurulumdan kuruluma değişir. Önce `rancher --help`
  çıktısını oku, ezberden komut yazma.

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

`kubectl delete pod` "zararsız" sanılır — deployment onu yeniden oluşturur.
Ama StatefulSet'te veri kaybına, tek replikalı serviste kesintiye yol açar.
Silmeden önce ne tarafından yönetildiğine bak.

Değişiklik istendiğinde önce `--dry-run=server` ile göster:

```bash
kubectl apply -f x.yaml --dry-run=server
kubectl diff -f x.yaml
```

## Konteyner çalışma zamanı

Küme dışı, tek makinedeki konteynerler için `podman-docker` becerisine geç.
RHEL ailesinde varsayılan `podman`'dır; `docker` genelde kurulu değildir.

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
