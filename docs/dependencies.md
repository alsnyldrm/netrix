# Bağımlılıklar ve lisanslar

Python doğrudan sürümleri `requirements.txt`, çözülmüş üretim ağacı `requirements.lock`, test araçları `requirements-dev.txt` içinde sabitlenmiştir. Frontend ağacı `package-lock.json` ile sabitlenir; Docker `npm ci --ignore-scripts` kullanır.

## Python üretim ağacı

| Paket | Sürüm | Lisans (dağıtım metadata) |
| --- | --- | --- |
| Mako | 1.4.3 | MIT |
| MarkupSafe | 3.0.4 | BSD-3-Clause |
| PyMySQL | 1.2.3 | MIT |
| SQLAlchemy | 2.1.6 | MIT |
| alembic | 1.20.1 | MIT |
| annotated-doc | 0.0.5 | MIT |
| annotated-types | 0.8.0 | MIT |
| anyio | 4.15.1 | MIT |
| argon2-cffi-bindings | 26.1.0 | MIT |
| argon2-cffi | 25.1.0 | MIT |
| async-timeout | 5.0.1 | Apache 2 |
| asyncssh | 2.24.1 | EPL-2.0 OR GPL-2.0-or-later |
| certifi | 2026.10.23 | MPL-2.0 |
| cffi | 2.1.1 | MIT-0 |
| click | 8.5.0 | BSD-3-Clause |
| cryptography | 50.0.2 | Apache-2.0 OR BSD-3-Clause |
| fastapi | 0.162.0 | MIT |
| h11 | 0.16.0 | MIT |
| httpcore | 1.0.9 | BSD-3-Clause |
| httpx | 0.28.1 | BSD-3-Clause |
| idna | 3.20 | BSD-3-Clause |
| opentelemetry-api | 1.45.1 | Apache-2.0 |
| pyasn1 | 0.6.5 | BSD-2-Clause |
| pycparser | 3.12 | BSD-3-Clause |
| pydantic-settings | 2.16.2 | MIT |
| pydantic | 2.14.2 | MIT |
| pydantic_core | 2.50.2 | MIT |
| pysnmp | 7.1.30 | BSD-2-Clause (wheel LICENSE.rst doğrulandı) |
| python-dotenv | 1.2.4 | BSD-3-Clause |
| redis | 8.1.0 | MIT |
| supervisor | 4.3.0 | BSD-derived (wheel LICENSES.txt) |
| starlette | 1.10.0 | BSD-3-Clause |
| typing-inspection | 0.4.4 | MIT |
| typing_extensions | 4.16.0 | PSF-2.0 |
| uvicorn | 0.54.0 | BSD-3-Clause |
| websockets | 17.3 | BSD-3-Clause |

## Frontend

| Paket | Sürüm | Lisans |
| --- | --- | --- |
| @fontsource/fira-code | 5.3.0 | OFL-1.1 |
| @fontsource/fira-sans | 5.3.0 | OFL-1.1 |
| @phosphor-icons/react | 2.1.10 | MIT |
| react | 19.3.1 | MIT |
| react-dom | 19.3.1 | MIT |
| @types/react | 19.3.0 | MIT |
| @types/react-dom | 19.3.0 | MIT |
| axe-core | 4.14.0 | MPL-2.0 (yalnızca test) |
| prettier | 3.9.10 | MIT |
| typescript | 7.0.2 | Apache-2.0 |
| vite | 8.3.5 | MIT |

## Değerlendirme

Kullanılan uygulama kütüphaneleri hazır network yönetim ürünü değildir. MIT/BSD/Apache lisanslı bileşenlerin bildirimleri korunur; fontlar OFL kapsamında kullanılır. AsyncSSH çift lisanslıdır; NETRIX dağıtımında EPL-2.0 seçeneği esas alınır ve değiştirilmemiş kütüphane kullanılır. Python ve Node çalışma zamanları, Redis (seçilen 8.2 sürümünün çoklu lisans seçeneklerinden AGPLv3) ve MariaDB istemcisi (GPLv2) ayrı altyapı bileşenleridir; kaynak kodları NETRIX motoru olarak gömülmez. Bu bileşenler değiştirilmedi; dağıtımda imaj/lisans bildirimleri korunmalıdır.

NETRIX için bağımsız bir açık kaynak lisansı verilmemiştir. Üçüncü taraf bileşenlerin hakları kendi lisanslarıyla yönetilir.

Resmi kaynaklar: [Redis lisans seçenekleri](https://redis.io/legal/licenses/), [AsyncSSH proje lisansı](https://github.com/ronf/asyncssh/blob/develop/COPYING), [PySNMP lisansı](https://github.com/lextudio/pysnmp/blob/main/LICENSE.rst). Python paketlerinin lisans dosyaları kurulu wheel dağıtımlarında korunur.

Tek container imajında Redis 8.2.2 binary'leri resmi `redis:8.2.2-bookworm` imajından alınır; Supervisor 4.3.0 süreçleri yönetir. MariaDB istemcisi Debian bookworm paketinden yüklenir; bu dağıtımda sürümü `1:10.11.19-0+deb12u1` olarak doğrulandı (`dpkg-query -W mariadb-client`). [Supervisor yapılandırması](https://supervisord.org/configuration.html) başlangıç/kapanış öncelikleri ve süreç yeniden başlatma davranışının kaynağıdır.
