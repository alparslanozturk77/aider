# aider-agent RPM'i — RHEL 9 ve 10 için.
#
# Tasarım kararı: bağımlılıklar RPM'e wheel olarak gömülür ve sanal ortam
# %post içinde --no-index ile kurulur. Kurulum anında AĞ GEREKMEZ; hedef
# çevrimdışı bir banka sunucusu.
#
# RHEL 9'un sistem python'ı 3.9, aider ise >=3.10 istiyor. Bu yüzden her iki
# sürümde de python3.12 kullanılır (RHEL 9'da AppStream'den gelir).

%global uygulama_dizini /opt/aider-agent
%global python_yorumlayici /usr/bin/python3.12
%global debug_package %{nil}

Name:           aider-agent
Version:        %{?surum}%{!?surum:0.1.0}
Release:        1%{?dist}
Summary:        Sistem yönetimi ajanı — aider forku, kurum içi endpoint ile çalışır

License:        Apache-2.0
URL:            https://github.com/alparslanozturk77/aider
Source0:        %{name}-%{version}.tar.gz

BuildRequires:  python3.12
Requires:       python3.12
Requires:       git

# Bağımlılıklar wheel olarak gömülü; RPM'in kendi bağımlılık çıkarımı
# bunları sistem paketi sanmasın.
AutoReqProv:    no

%description
Aider'ın sistem yönetimi ajanına dönüştürülmüş forku. Kurum içi, çevrimdışı
bir OpenAI uyumlu endpoint (Qwen) ile çalışır: agentic araç döngüsü, üç
katmanlı izin sistemi, MCP istemcisi ve RHEL odaklı beceriler.

Kurulum ağa çıkmaz; bağımlılıklar paketin içinde wheel olarak gelir.

%prep
%setup -q

%build
# Derleme yok: wheel'ler hazır gelir.

%install
rm -rf %{buildroot}
mkdir -p %{buildroot}%{uygulama_dizini}
cp -a . %{buildroot}%{uygulama_dizini}/

mkdir -p %{buildroot}%{_bindir}
cat > %{buildroot}%{_bindir}/aider-agent <<'SARMALAYICI'
#!/bin/sh
exec /opt/aider-agent/.venv/bin/aider "$@"
SARMALAYICI
chmod 0755 %{buildroot}%{_bindir}/aider-agent

%post
# Sanal ortamı kurulum anında, ağa çıkmadan oluştur.
%{python_yorumlayici} -m venv %{uygulama_dizini}/.venv
%{uygulama_dizini}/.venv/bin/python -m pip install --quiet --no-index \
    --find-links %{uygulama_dizini}/wheels \
    -r %{uygulama_dizini}/requirements.txt
# Editable kurulum çevrimdışı çalışmıyor (setuptools>=68 indirmeye çalışıyor);
# aider-agent'ın kendi wheel'i pakete gömülü.
%{uygulama_dizini}/.venv/bin/python -m pip install --quiet --no-index --no-deps \
    --find-links %{uygulama_dizini}/wheels aider-chat

# Beceriler tüm projelerde görünsün diye ev dizinine değil, sistem geneline
# bağlanır; aider AIDER_SKILLS_PATH ile de okuyabilir.
echo "aider-agent kuruldu: %{uygulama_dizini}"
echo "Beceriler programla birlikte kuruldu; her dizinde görünürler."
echo "Modeli tanımlamak için: aider-agent  ->  /model-ekle"

%postun
if [ $1 -eq 0 ]; then
    rm -rf %{uygulama_dizini}/.venv
fi

%files
%license LICENSE.txt
%doc README.md AGENT.md BIRLESTIRME.md
%{uygulama_dizini}
%{_bindir}/aider-agent

%changelog
* Sat Aug 29 2026 alparslanozturk77 <alparslan.ozturk@gmail.com> - 0.1.0-1
- İlk paket: agent katmanı v0.1.0
