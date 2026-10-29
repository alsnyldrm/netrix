# NETRIX

**Network Intelligence, Discovery & Management Platform**

Akıllı Ağ Keşif ve Yönetim Platformu

NETRIX, ortak cihaz envanteri üzerinde çalışan IPAM/ağ keşfi, konfigürasyon sürümleme ve ağ izleme platformudur. Python/FastAPI backend, MariaDB, Redis, aynı container içindeki Python worker/zamanlayıcı süreçleri ve özgün Türkçe React arayüzü içerir. NetBox/Oxidized/LibreNMS/Zabbix motoru kullanılmaz.

## Dağıtım

Tek servisli Compose stack: `netrix`; tek container: `netrix`. API/arayüz, Redis, worker ve zamanlayıcı Supervisor ile aynı container içinde çalışır; migration servisler açılmadan uygulanır. Redis verisi kalıcı volume'dadır.

Hedef: `10.2.0.87:/opt/netrix`, harici MariaDB `10.2.0.31/netrix`. Dış adres `https://netrix.fbu.edu.tr`; host Nginx → `127.0.0.1:8101`.

```bash
cp .env.example .env
# .env içindeki DB URL'sini ve rastgele anahtarları güvenli ortamda ayarlayın.
mkdir -p secrets
chmod 700 secrets
chmod 600 .env
touch secrets/known_hosts
chmod 644 secrets/known_hosts
docker compose config --quiet
docker compose build
docker compose up -d
docker compose ps
```

Şifreleme anahtarı üretimi: `python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'`. Kurulum token'ı üretimi: `python -c 'import secrets; print(secrets.token_urlsafe(32))'`. Bu komutları yalnızca kendi güvenli terminalinizde çalıştırın; çıktıları Git'e yazmayın. DB URL parolasında URL encoding kullanın.

İlk ziyarette dağıtımda oluşturulan güvenli kurulum dosyasındaki anahtarla yönetici hesabınızı oluşturun. Sabit varsayılan kullanıcı/parola yoktur. Ardından **Erişim kasası → Lokasyon/VRF → Cihaz veya Ağ keşfi kapsamı → Manuel keşif → Görev merkezi** akışını izleyin. Gerçek ağ sorguları kendiliğinden başlamaz; zamanlama/izleme açıkça etkinleştirilmelidir.

## Geliştirme ve doğrulama

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest -q
.venv/bin/ruff check backend tests scripts
cd frontend
npm ci
npm run build
```

Birim/API testleri gerçek ağ bağlantılarını engeller. Tarayıcı fixture sunucusu, üretim veritabanından ayrı `.secrets/browser.db` kullanır: `PYTHONPATH=backend .venv/bin/python tests/ui_server.py`; ardından `.venv/bin/python scripts/browser_check.py`. Tarayıcı akışı yalnızca yerel test sunucusuna yöneliktir. Playwright Chromium önceden kurulmalıdır.

MariaDB entegrasyonu yalnızca `netrix_test` adlı atılabilir DB'ye uygulanır: Alembic upgrade sonrası `PYTHONPATH=backend python scripts/mariadb_check.py`. Üretim veritabanında test amacıyla schema drop yapılmaz.

API dokümantasyonu `/api/v1/docs`, liveness `/api/v1/health/live`, DB/Redis readiness `/api/v1/health/ready`.

## Belgeler

- [Çalışan mimari ve davranış sınırları](docs/architecture.md)
- [İşletim, yedekleme ve geri yükleme](docs/operations.md)
- [Doğrulama kayıtları](docs/verification.md)
- [Bağımlılıklar ve lisanslar](docs/dependencies.md)
- [Proje yönergeleri](AGENTS.md)
- [Ayrıntılı hedef veri modeli](docs/data-model.md)
- [Geliştirme sırası](docs/development-plan.md)
- [UI UX Pro Max tasarım sistemi](design-system/netrix/MASTER.md)

## Lisans

NETRIX için açık kaynak lisansı seçilmemiştir. Deponun public olması yeniden kullanım lisansı vermez. Kullanılan kütüphanelerin lisansları kendilerine aittir.
