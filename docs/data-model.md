# NETRIX kapsamlı veri modeli

> **29 Ekim 2026 güncellemesi:** Proje sahibi harici MariaDB ve üç modülün arayüz/motorlarıyla birlikte teslimini istedi. Bu belgedeki PostgreSQL/TimescaleDB seçimleri eski hedef tasarıma aittir. Çalışan MariaDB tür eşlemeleri, süreçler ve uygulanan davranışlar için [mimariyi](architecture.md) ve migration dosyalarını esas alın.
Bu belge hedef ilişkisel modeli tanımlar; uygulanmış şema değildir. İlk aşamada kimlik, envanter, IPAM, erişim profilleri ve keşif tabloları oluşturulur. Diğer tablolar ilgili modülle birlikte migration'a eklenir. Başlangıç tek kuruluş içindir; VRF ve site ayrımları kiracı izolasyonu yerine geçmez.

## Ortak kurallar

- İş varlıklarında `id UUID`, `created_at TIMESTAMPTZ`, `updated_at TIMESTAMPTZ` kullan. Değişmez olay ve gözlemlerde yalnızca olay/kayıt zamanı yeterlidir. Zaman serilerinin anahtarları aşağıda ayrıca tanımlanır.
- FK alanlarını indeksle; bileşik unique indeksin zaten kapsadığı alan için gereksiz indeks üretme. Kritik alanları JSONB yerine tipli kolonlarla sakla; JSONB üreticiye özgü ek bilgiler içindir.
- IPv4/IPv6 adreslerinde PostgreSQL `INET`, ağ bloklarında `CIDR`, donanım adreslerinde `MACADDR` kullan. MAC değeri olmayan arayüzleri destekle; MAC adresini cihazın tekil kimliği kabul etme.
- Durumları sınırlandır: cihaz yaşam döngüsü `planned/active/maintenance/retired`; görev `queued/running/succeeded/partial/failed/cancelled`; atama `reserved/active/deprecated`. Erişilebilirlik yaşam döngüsünden ayrı tutulur.
- Keşif kanıtlarını eklemeli sakla; güncel envantere uygulanmalarını servis katmanında transaction içinde yap. Son görülme zamanı yalnızca başarılı gözlemle ilerlesin; eksik yanıt kaydı otomatik silmesin.
- Envanterde emeklilik/arşivleme kullan. Fiziksel silmede FK davranışını açık tanımla; audit, konfigürasyon ve olay geçmişini zincirleme silme. Geçmişte gereken ad/kimlik özetlerini olay kaydına ekle.

## 1. Merkezi kimlik ve denetim

| Tablo | Ana alanlar | İlişkiler ve kısıtlar |
| --- | --- | --- |
| `users` | email, display_name, password_hash, is_active, last_login_at | Büyük/küçük harften bağımsız tekil email |
| `roles` | name, description | Tekil name; başlangıç rolleri admin/operator/viewer |
| `permissions` | resource, action | Tekil (resource, action) |
| `user_roles` | user_id, role_id | Birleşik PK; iki FK |
| `role_permissions` | role_id, permission_id | Birleşik PK; iki FK |
| `auth_sessions` | user_id, refresh_token_hash, expires_at, revoked_at | Ham token saklanmaz; user FK |
| `api_tokens` | user_id, name, token_hash, expires_at, revoked_at | Token yalnızca oluşturulurken gösterilir; yetkileri kullanıcı yetkilerini aşamaz |
| `audit_events` | occurred_at, actor_user_id, action, entity_type, entity_id, request_id, redacted_changes JSONB | Aktör nullable FK; hedef UUID polimorfik referans, doğrudan FK değildir |

Yetkilendirmeyi HTTP ve WebSocket erişimine uygula. Audit kaydında credential, token veya hassas konfigürasyon içeriği bulunmasın.

## 2. Merkezi cihaz envanteri

MariaDB uygulama notu (30 Ekim 2026): `device_types(id, code, name, description)` kataloğu uygulanmıştır. `devices.kind`, değişmez `device_types.code` değerine FK ile bağlanır; görünen ad bağımsız düzenlenir. Aktif/arşiv cihaz ilişkileri silmeyi engeller. Varsayılan `other` kaydı, sınıflandırılmamış cihazlar için korunur.

| Tablo | Ana alanlar | İlişkiler ve kısıtlar |
| --- | --- | --- |
| `sites` | name, code, description, timezone | Tekil code |
| `locations` | site_id, parent_id, name | Site FK; parent aynı sitede olmalı, döngü engellenmeli |
| `vendors` | name | Tekil name |
| `device_models` | vendor_id, model, device_kind, capabilities JSONB | Tekil (vendor_id, model); switch/router/firewall/other |
| `devices` | name, hostname, site_id, location_id, model_id, serial_number, lifecycle_status, last_seen_at | Seri numarası küresel tekil kabul edilmez; hostname zorunlu tekil değildir |
| `device_endpoints` | device_id, vrf_id, address INET, protocol, port, is_primary | Tekil (device_id, vrf_id, address, protocol, port); tek host adresi; cihaz/protokol başına en fazla bir primary |
| `device_identifiers` | device_id, kind, value, source, confidence | SNMP engine ID, LLDP chassis ID gibi kimlikler; tekil (device_id, kind, value); eşleşme çatışmaları servis katmanında çözülür |
| `interfaces` | device_id, name, if_index, if_type, description, mac_address, speed_bps BIGINT, admin_status, oper_status, mtu, last_seen_at | Tekil (device_id, name); mevcut if_index cihaz içinde nullable tekil; ifIndex değişimi geçmiş arayüz kimliğini değiştirmemeli |
| `interface_memberships` | parent_interface_id, member_interface_id, kind | LAG/breakout; kendine bağ ve döngü engellenir |
| `tags` / `device_tags` | name / device_id, tag_id | Tekil tag adı; birleşik atama PK |

`device_endpoints` erişim hedefidir; IP sahipliğinin kaynağı IPAM atamalarıdır. `devices` içinde ikinci bir serbest metin yönetim IP'si tutma. Endpoint adresinin aynı VRF'deki IPAM kaydıyla tutarlılığını servis katmanında sağla. Cihazlarda site ve location uyumunu doğrula.

## 3. IPAM ve VLAN

| Tablo | Ana alanlar | İlişkiler ve kısıtlar |
| --- | --- | --- |
| `vrfs` | name, route_distinguisher, description | Tekil name; varsayılan/global VRF de gerçek bir satırdır |
| `vlan_domains` | name, site_id | VLAN kimliklerinin tekrar kullanılabildiği L2 kapsamı |
| `vlans` | domain_id, vid, name, description | `1 <= vid <= 4094`; tekil (domain_id, vid) |
| `prefixes` | vrf_id, parent_id, network CIDR, site_id, vlan_id, status, description | Tekil (vrf_id, network); parent aynı VRF'de üst ağ olmalı; IPv4 ve IPv6 desteklenir |
| `ip_addresses` | vrf_id, address INET, dns_name, status, description | Tekil (vrf_id, address); yalnızca /32 veya /128 host maskesi |
| `ip_assignments` | ip_address_id, interface_id, assignment_kind, is_primary | Tekil (ip_address_id, interface_id); anycast/virtual/shared atamalar açıkça belirtilir |
| `interface_vlans` | interface_id, vlan_id, mode | Tekil (interface_id, vlan_id); access/tagged/native; port başına en fazla bir access veya native VLAN, mod uyumu doğrulanır |
| `ip_change_events` | occurred_at, ip_address_id, discovery_run_id, change_kind, old_value JSONB, new_value JSONB | IP/MAC/hostname/atama değişim geçmişi; hassas veri içermez |

IP'nin kapsandığı ağları adres kapsama sorgusuyla bul; iç içe prefix'lerde en uzun prefix güncel alt ağı belirler. Aynı VRF'de hiyerarşik ağlara izin ver, belirsiz çakışmaları reddet. VLAN ve prefix ilişkisi isteğe bağlıdır; VLAN birden fazla prefix taşıyabilir. Birincil IP ataması arayüz ve adres ailesi başına en fazla bir tanedir. Bir IP'nin birden fazla arayüze atanması yalnızca açık shared/anycast politikasıyla mümkündür.

Kullanım oranını aktif/rezerve adreslerden hesapla; büyük IPv6 blokları için tüm adresleri önceden satır olarak üretme. IPv4 ağ/yayın adresi kurallarını prefix uzunluğuna göre uygula; /31 ve /32'yi ayrıca ele al.

## 4. Cihaz erişimi ve sırlar

| Tablo | Ana alanlar | İlişkiler ve kısıtlar |
| --- | --- | --- |
| `credential_profiles` | name, protocol, username, encrypted_payload, key_version, metadata JSONB | SNMPv3/SSH/API; ciphertext gerekli nonce/tag bilgilerini taşır |
| `device_credentials` | device_id, credential_profile_id, priority | Tekil (device_id, credential_profile_id); protokol/yetenek uyumu |
| `ssh_host_keys` | device_id, endpoint_id, algorithm, fingerprint, trusted_at, trusted_by | Tekil (endpoint_id, algorithm); beklenmeyen anahtar değişimi hata/olay üretir |

Şifreli payload: SNMPv3 auth/privacy sırları, SSH parola/özel anahtar veya API token. Algoritma ve güvenlik seviyesi doğrulanır; SNMPv3 için authPriv varsayılandır. API yalnızca maskelenmiş profil bilgisini döndürür. Anahtar sürümü rotasyonu mümkün kılar. Konfigürasyon yedekleri de sır içerebilir; aynı koruma yaklaşımıyla şifrelenir.

## 5. Kuyruk, zamanlama ve keşif

| Tablo | Ana alanlar | İlişkiler ve kısıtlar |
| --- | --- | --- |
| `job_schedules` | name, job_kind, cron_expression, timezone, enabled, next_run_at, parameters JSONB | Zamanlama parametreleri tür bazında doğrulanır |
| `job_runs` | schedule_id, job_kind, status, idempotency_key, queued_at, started_at, heartbeat_at, finished_at, attempt, error_code, redacted_error | Tekil idempotency_key; retry aynı mantıksal işi tekrar güvenle çalıştırır |
| `discovery_scopes` | name, vrf_id, site_id, target_prefix CIDR, excluded_targets JSONB, methods, timeout_ms, concurrency_limit, enabled | İzin verilen hedef kapsamı; hariç tutmalar ve yöntemler doğrulanır |
| `discovery_runs` | job_run_id, scope_id, scope_snapshot JSONB, targets_total, targets_completed, devices_found | Job FK tekil; kapsamın çalışma anındaki hali saklanır |
| `discovery_observations` | run_id, observed_at, target_address INET, observation_kind, source, evidence JSONB, confidence, resolved_device_id | Kimlik, hostname, ARP/NDP, FDB, LLDP/CDP gözlemleri; cihaz eşleşmesi nullable |
| `mac_locations` | vrf_id, vlan_id, mac_address, switch_interface_id, source, confidence, first_seen_at, last_seen_at | Güncel FDB konumu; MAC birden fazla portta görülebilir, küresel tekil değildir |
| `endpoint_bindings` | ip_address_id, mac_address, observed_interface_id, source, confidence, first_seen_at, last_seen_at | ARP/NDP ve FDB korelasyonu; uplink üzerinde görülen MAC doğrudan fiziksel bağlantı kanıtı değildir |
| `topology_links` | local_interface_id, remote_interface_id, remote_chassis_id, remote_port_id, protocol, confidence, first_seen_at, last_seen_at, expires_at | Çözülemeyen uzak uç nullable; LLDP/CDP kanıtına dayalı bağlantı |
| `topology_change_events` | occurred_at, link_id, run_id, change_kind, details JSONB | Oluşma, değişme ve kaybolma geçmişi |

Redis yürütme kuyruğudur; iş durumu ve kalıcı geçmiş PostgreSQL'dedir. En az bir kez teslim varsayılır; retry transaction/upsert ve idempotency ile yönetilir. DB kaydı ile kuyruğa iletim arasındaki kayıplar transactional outbox ile önlenir: `outbox_events(id, topic, payload, created_at, published_at, attempts)` ve tekrar güvenli yayınlayıcı kullanılır. Aynı hedefte çakışan çalışmaları lease/lock ile sınırla; worker kaybında heartbeat süresi dolan işler geri alınabilsin.

Topoloji güncel ilişkileri ve olay geçmişini ayırır. Çift yönlü LLDP/CDP gözlemlerini normalize ederek aynı linkte birleştir; eski gözlemleri TTL ile bayat olarak işaretle. Loop, LAG ve birden fazla uplink bulunduğunda topolojiyi zorunlu bir ağaç gibi modelleme. Fiziksel port tespitinde ARP/NDP → MAC → VLAN → FDB → switch port zincirini kullan ve kanıt yetersizliğini raporla.

## 6. Konfigürasyon yönetimi

| Tablo | Ana alanlar | İlişkiler ve kısıtlar |
| --- | --- | --- |
| `config_backup_policies` | name, schedule_id, retention_days, enabled | Cihaz eşlemesi `device_backup_policies(device_id, policy_id)` üzerinden |
| `config_snapshots` | device_id, job_run_id, collected_at, config_kind, content_hash, encrypted_content, key_version, byte_size, adapter_version | running/startup gibi türler; hash normalize edilmiş içerikten; her toplama kaydı korunur |
| `config_diffs` | device_id, old_snapshot_id, new_snapshot_id, created_at, added_lines, removed_lines, encrypted_diff, key_version | Tekil (old_snapshot_id, new_snapshot_id); iki snapshot aynı cihaz/türden olmalı |
| `config_change_events` | device_id, diff_id, detected_at, severity | Alarm motoruna kaynak |

Ham çıktıyı sakla; karşılaştırma için üreticiye özgü zaman damgası gibi değişken satırları ayrı normalizasyon adımında ele al. Satır bazında diff üret; ilk snapshot değişiklik alarmı değildir. API diff görünümünde sırları maskele; ham indirmeyi ayrı yetkiye bağla. Retention, diff referanslarını ve olay geçmişini korumalıdır.

## 7. Monitoring ve TimescaleDB

| Tablo | Ana alanlar | İlişkiler ve kısıtlar |
| --- | --- | --- |
| `monitoring_policies` | name, poll_interval_seconds, retention_days, enabled, parameters JSONB | Cihaz eşlemesi `device_monitoring_policies(device_id, policy_id)` üzerinden |
| `interface_samples` | time, interface_id, in_octets, out_octets, in_errors, out_errors, in_discards, out_discards, counter_bits, uptime_ticks, discontinuity_ticks, oper_status, speed_bps | Hypertable; PK (interface_id, time); unsigned 64 bit sayaçlar NUMERIC(20,0) |
| `interface_rates` | time, interface_id, interval_seconds, in_bps, out_bps, in_utilization_pct, out_utilization_pct, quality | Hypertable; PK (interface_id, time); geçersiz hız nullable |
| `device_samples` | time, device_id, availability, response_ms, cpu_pct, memory_used_bytes, memory_total_bytes, uptime_seconds | Hypertable; PK (device_id, time); desteklenmeyen metrik nullable |
| `monitoring_events` | occurred_at, device_id, interface_id, event_kind, previous_value, current_value | Durum geçişleri, sayaç sıfırlanması, erişim hataları |

- `bps = (yeni_octets - eski_octets) * 8 / geçen_saniye`; Mbps için 10^6, Gbps için 10^9 kullan. Trafik bit/s, sayaçlar byte cinsindedir.
- SNMP 64 bit high-capacity sayaçlarını tercih et. Reboot, discontinuity ve sayaç genişliğini kontrol et; doğrulanamayan wrap/reset ve örnek aralıklarında hız üretme. Eksik veri sıfır trafik değildir.
- Utilization hesabında örnek anındaki port hızını kullan; hız bilinmiyorsa yüzdeyi boş bırak. Full duplex giriş/çıkışı ayrı hesapla.
- Her hypertable unique anahtarı zaman bölümleme kolonunu içermelidir. Zaman aralığı/varlık sorgularına uygun indeks ve cihaz başına veri hacmine uygun chunk aralığı belirle.
- Ham veri ve saatlik/günlük özetler için ayrı retention politikaları tanımla. Sıkıştırma ve continuous aggregate ayarlarını seçilen TimescaleDB sürümüne göre migration/kurulumda doğrula.

## 8. Alarm ve bildirim

| Tablo | Ana alanlar | İlişkiler ve kısıtlar |
| --- | --- | --- |
| `alert_rules` | name, module, metric_or_event, operator, threshold, duration_seconds, recovery_threshold, severity, enabled, selector JSONB | Eşik, histerezis ve hedef seçimi tür bazında doğrulanır |
| `alert_instances` | rule_id, entity_type, entity_id, state, opened_at, last_evaluated_at, resolved_at, acknowledged_by, acknowledged_at | pending/firing/resolved; kural/hedef başına en fazla bir açık olay; onay durumu ayrı tutulur |
| `alert_events` | instance_id, occurred_at, previous_state, new_state, observed_value, reason | Değişmez geçiş geçmişi |
| `notification_channels` | name, channel_kind, encrypted_settings, key_version, enabled | Kanal sırları şifreli saklanır |
| `alert_routes` | rule_id, channel_id | Tekil (rule_id, channel_id) |
| `notification_deliveries` | alert_event_id, channel_id, status, attempts, next_attempt_at, delivered_at, redacted_error | Tekil (alert_event_id, channel_id); tekrar güvenli gönderim |

No-data, erişilememe ve eşik aşımını ayrı değerlendir. Yetkilendirilmiş WebSocket abonelerine commit sonrası olay gönder; yeniden bağlantıda kaçırılan durumu REST API ile sorgulat.

## 9. İlişki özeti ve doğrulama

- Site → konumlar/cihazlar; üretici → modeller → cihazlar → arayüzler.
- VRF → prefix'ler/IP'ler; VLAN domain → VLAN'lar; arayüz ↔ IP/VLAN atamaları.
- Cihaz ↔ credential profilleri; kapsam → keşif çalışmaları → gözlemler → envanter/topoloji olayları.
- Cihaz → konfigürasyon snapshot'ları → diff'ler; arayüz → trafik örnekleri/hızları.
- Kural → alarm örnekleri → geçiş olayları → bildirim teslimleri.

Migration testlerinde FK/unique/check kısıtlarını ve sorgu indekslerini doğrula. Özellikle farklı VRF'de aynı IP, aynı VLAN numarasının farklı domain'de kullanımı, IPv6, LAG, değişen ifIndex, yinelenen görev teslimi, kayıp worker ve sıfırlanan sayaç senaryolarını kapsa. Satırlar arası/döngü gibi basit CHECK ile ifade edilemeyen kuralları transaction içindeki servis doğrulaması ve gerektiğinde kilit/trigger ile uygula; eşzamanlılık testini ekle.

## Uygulanan IPAM genişletmesi (31 Ekim 2026)

Alembic `20261031_13`: `dns_servers`, şifreli `integrations`, kaynak/kimlik başına tekil `ip_observations`, kaynak/zaman başına tekil `ip_traffic`; prefix DNS/VLAN cihazı/kapsam FK’leri, kullanım eşiği ve ping/keşif zamanlamaları; IP manuel işletim sistemi/kabinet/lokasyon alanları. Tarihler MariaDB `DATETIME(6)` ve API’de UTC’dir. Otomatik gözlemler manuel alanları değiştirmez; mevcut ortak cihaz/arayüz/IP envanteri kullanılır. Entegrasyon yetkili blokları servis tarafından doğrulanan JSON kimlik listesidir; kullanılan prefix silinmesi servis katmanında engellenir. Ayrıntı: [IPAM işleyişi](ipam-integrations.md).

## IPAM tanım menüleri (31 Ekim 2026)

Alembic `20261031_14`: `cabinets(id, name, site_id, description)` ve `operating_systems(id, name, description)` katalogları. Her iki ad tekildir; kabinetin opsiyonel lokasyonu mevcut `sites` tablosuna indeksli FK ile bağlıdır. Zaman alanları `DATETIME(6)`/UTC'dir. Kataloglar başlangıçta boştur; dolu kataloglarla downgrade engellenir. Ortak `sites` ekranı IP adres yönetimi menüsüne taşınmıştır; cihaz ve ağ bloğu ilişkileri aynı kayıtlara bağlı kalır.

IP formu bu kataloglardan ve ortak lokasyonlardan ad önerileri sunar; IP üzerindeki mevcut manuel metin alanları korunur. Öneri seçimi adı metin olarak kaydeder; katalog adını düzenlemek/silmek geçmiş IP değerlerini değiştirmez. Kaynaklardan gelen OS/konum gözlemleri ayrı kalır. Kabinet ve işletim sistemi CRUD işlemleri merkezi yetkilendirme, audit ve doğrulama katmanını kullanır.


## Kurum/lokasyon hiyerarşisi ve kabinet yerleşimi (31 Ekim 2026)

Alembic `20261031_15`: `institutions`, `rack_placements` ve `model_images` tabloları; `sites.institution_id/parent_id`, `prefixes.institution_id/scan_authorized`, `cabinets.sub_site_id/units/lock_version`, `ip_addresses.device_id`. İlişkiler indeksli FK, cihaz başına tek yerleşim UNIQUE ve kapasite/konum CHECK ile korunur. Kurum ve kabinet sürüm alanları kod dağıtımı/yerleşim yarışlarını serileştirir. Kurum gerekliliği ve iki seviyeli lokasyon sınırı servis doğrulamasındadır; eski lokasyonların kurum alanı veri kaybı olmadan boş kalır. Aynı kabinet içindeki U çakışması, kabinet satırının kilidi altında doğrulanır. Üretici görsel eşlemesi `(vendor, model)` başına tekildir. Yeni veriler doluyken kayıplı downgrade engellenir. Zamanlar `DATETIME(6)`/UTC'dir.

## IP adresi konum ilişkileri (31 Ekim 2026)

Alembic `20261031_17`, `ip_addresses.institution_id/site_id/sub_site_id` için nullable, indeksli FK'ler ekler. IP düzenleme formu kurum, ana lokasyon ve alt lokasyonu ayrı seçer; API aynı kurumdaki ana lokasyon ve ona bağlı alt lokasyon ilişkisini doğrular. Üst ilişki değiştiğinde toplu düzenleme eski alt ilişkileri temizler. Eski `location` metni uyumluluk için tutulur; ilişki seçildiğinde yaprak lokasyon adıyla güncellenir. Eski manuel adlardan yalnızca benzersiz, kurumlu eşleşmeler taşınır; belirsiz ve eşleşmeyen metinler korunur. Yeni ilişkiler doluyken kayıplı downgrade engellenir.

## Pasif kabinet organizerleri (31 Ekim 2026)

Alembic `20261031_18`, `rack_accessories` tablosunu ekler: indeksli `cabinet_id` FK, `kind=brush_organizer`, `start_unit`, `units`, UUID ve UTC zamanlar. Tür ve 1–60 U sınırları CHECK ile korunur. Cihaz/organizer U çakışmaları ve kabinet kapasitesi, aynı kabinet satır kilidi altında servis tarafından doğrulanır. Organizer cihaz/IP envanteri oluşturmaz. Kayıt varken veri kaybettiren downgrade engellenir.

## IPAM'dan ortak kabinet envanteri (31 Ekim 2026)

`20261031_19` mevcut `device_types` kataloğuna yalnızca eksikse `storage` / Storage ve `san_switch` / SAN Switch değerlerini ekler; aynı kod veya adı olan kullanıcı kayıtlarını değiştirmez. Downgrade katalog verisini korur. Yeni tablo yoktur. IP'den kabinet yerleştirme, aynı `(vrf_id, management_ip)` tekilliğini ve mevcut `rack_placements` tablosunu kullanır. VRF/kabinet kilitleri, güncel kilitli okumalar ve geçici MariaDB eşzamanlılık hatasında bir işlem tekrarı yinelenen cihazları önler. Kabinet yerleşimi başarısızsa yeni cihaz oluşturma da geri alınır; IP'nin üst switch/port ilişkisi korunur.
