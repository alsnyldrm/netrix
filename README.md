# NETRIX

**Network Intelligence, Discovery & Management Platform**

Akıllı Ağ Keşif ve Yönetim Platformu

NETRIX; merkezi cihaz envanterini paylaşan IPAM ve ağ keşfi, konfigürasyon yönetimi ve ağ izleme modüllerinden oluşacak web tabanlı bir platformdur.

Hedef altyapı: Python/FastAPI, PostgreSQL/TimescaleDB, Redis, özel Python worker servisleri, WebSocket ve Docker Compose. Cihaz erişimi SNMPv3, SSH ve REST API üzerinden; komşuluk keşfi LLDP/CDP verileriyle sağlanacaktır.

## Durum

Depo şu anda proje yönergelerini, hedef veri modelini ve geliştirme planını içerir. Backend, worker ve Compose servisleri henüz uygulanmamıştır.

## Belgeler

- [Proje ve ajan yönergeleri; beceri/MCP seçimi](AGENTS.md)
- [Kapsamlı veri modeli](docs/data-model.md)
- [Kabul ölçütleriyle ilk geliştirme adımları](docs/development-plan.md)

İlk aşama; altyapı, merkezi kimlik doğrulama, cihaz envanteri, temel IPAM ve keşif motorudur. Hazır ağ yönetim ürünleri yerine NETRIX'e özel motorlar geliştirilecektir.

## Lisans

Henüz bir açık kaynak lisansı seçilmemiştir. Deponun public olması yeniden kullanım için lisans verildiği anlamına gelmez.
