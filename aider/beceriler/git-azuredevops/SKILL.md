---
name: git-azuredevops
description: Git işlemleri ve Azure DevOps üzerinde çalışırken kullan — dal, commit, PR, pipeline, merge çakışması. "git", "commit", "branch", "dal", "PR", "pull request", "merge", "azure devops", "pipeline", "repo" isteklerinde tetiklenir.
---

## Önce nerede olduğunu bil

```bash
git status
git branch --show-current
git log --oneline -5
git remote -v
```

Bunlara bakmadan commit, merge ya da push yapma.

## Salt-okunur keşif

```bash
git diff                          # çalışma ağacı
git diff --staged                 # sahnelenmiş
git diff <dal>...HEAD             # dalın getirdikleri (üç nokta)
git log --oneline --graph -20
git log -S "<ifade>"              # bir metnin ne zaman girdiğini bul
git blame -L 40,60 <dosya>
git show <commit>
```

`git log -S` bir hatanın ne zaman girdiğini bulmanın en hızlı yoludur.

## Commit

Ana dalda çalışıyorsan **önce dal aç**:

```bash
git checkout -b ozellik/kisa-ad
```

Commit mesajı: ilk satır 72 karakteri geçmesin, emir kipi, *ne* değil *neden*.
Gövdede bağlam ver. Depoda mevcut mesajların diline uy — `git log -10` ile bak.

```bash
git add <belirli-dosyalar>        # 'git add .' yerine seçerek ekle
git commit
```

`git add -A` ile istemeden bir şey eklemek kolaydır. Commit öncesi
`git diff --staged` ile ne eklediğine bak.

## Azure DevOps

Kimlik: `az login` ya da PAT (Personal Access Token). Kurumda genelde PAT
kullanılır ve `AZURE_DEVOPS_EXT_PAT` ortam değişkeninde durur.

```bash
az devops configure --defaults organization=https://dev.azure.com/<kurum> project=<proje>

az repos list -o table
az repos pr list --status active -o table
az repos pr show --id <id>
az pipelines runs list --top 10 -o table
az pipelines runs show --id <id>
```

PR açma:

```bash
git push -u origin ozellik/kisa-ad
az repos pr create \
    --source-branch ozellik/kisa-ad \
    --target-branch main \
    --title "Kısa başlık" \
    --description "Ne değişti ve neden."
```

`az` yoksa ya da komut hata veriyorsa: `az devops --help` ve
`az repos pr --help` ile sürümündeki alt komutları doğrula. Azure CLI
eklentileri sürümden sürüme değişir; ezberden parametre yazma.

Çevrimdışı kurumda `az` kurulu olmayabilir. O durumda PR'ı web arayüzünden
aç; git tarafını buradan hallet, kullanıcıya push edilen dal adını ver.

## Merge çakışması

```bash
git status                        # hangi dosyalar çakıştı
git diff --name-only --diff-filter=U
```

Her dosyayı aç, `<<<<<<<` `=======` `>>>>>>>` işaretlerini bul. **İki tarafı da
oku** — çakışmayı bir tarafı silerek çözmek en sık yapılan hatadır.

```bash
git add <cozulmus-dosya>
git commit                        # merge mesajı otomatik gelir
```

Vazgeçmek: `git merge --abort`

Fork'ta upstream birleştirmesi yapıyorsan `upstream-birlestir` becerisine geç.

## Tehlikeli komutlar

Bunları onay almadan çalıştırma:

| Komut | Ne olur |
|---|---|
| `git push --force` | Uzaktaki commit'leri siler, başkasının işini yok eder |
| `git reset --hard` | Commit edilmemiş her şeyi geri dönüşsüz siler |
| `git clean -fdx` | İzlenmeyen dosyaları siler — `.env` dahil |
| `git rebase` (paylaşılan dalda) | Geçmişi yeniden yazar, diğerlerini bozar |
| `git checkout -- <dosya>` | O dosyadaki değişiklikleri siler |

`--force` yerine `--force-with-lease` kullan: başkası araya commit attıysa
durur.

Commit edilmemiş iş varken dal değiştirmen gerekiyorsa `git stash` kullan,
`reset --hard` değil.

## Raporlama

Ne yaptığını commit hash'i ve dal adıyla söyle. PR açtıysan URL'sini ver.
Push etmediysen etmediğini açıkça belirt — kullanıcı işin uzakta olduğunu
sanmasın.
