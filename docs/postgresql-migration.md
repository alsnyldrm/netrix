# PostgreSQL: menü sahipliği ve veri aktarımı

6 Kasım 2026 kararı: mevcut üç düğümlü PostgreSQL kümesinin **10.2.0.31:5432** yazma VIP'si kullanılır. NETRIX için SQL sunucusu, PostgreSQL servisi veya SQL container'ı kurulmaz. Veritabanı `netrix`; uygulama `netrix_app`, migration hesabı `netrix_owner` kullanır. Rastgele parolalar yalnız uygulama sunucusundaki 0600 secret/ortam dosyalarındadır.

## Sahiplik

Her ana menünün şeması vardır. `public`, `ortak`, `kaynaklar` altında uygulama tablosu bulunmaz. Her tablonun tek sahibi bir menüdür; cihaz kayıtları `envanter.devices` içinde bir kez tutulur. Menü servisleri başka menünün verisini tam nitelikli ilişkilerle okuyabilir; tabloyu kendi şemasına kopyalamaz. Altyapı kayıtları da tanımlı sahibine gider: görevler `operasyon.jobs`, denetim `yonetim.audit_events`. Ağ kaynaklarının yazım sözleşmeleri, tablo sahibi servis tarafından yürütülür.

Otorite `backend/netrix/db_layout.py` içindeki kapalı listedir. Liste dışı tablo model yüklenirken reddedilir. FK'ler `schema.table.column` hedeflidir; `search_path` sırasıyla tablo seçilmez. `genel_bakis` yalnız okur, bu nedenle kendi veri kopyası yoktur ve şeması boştur. Alembic sürümü Yönetim'in `yonetim.alembic_version` tablosundadır.

## Türler ve eşzamanlılık

- Mevcut kimlikler ve dış sistem referansları dönüşümde korunur. UUID metinlerinin API sözleşmesi değişmez.
- Olay zamanları `TIMESTAMPTZ` olur; bağlantı saat dilimi UTC'dir. API yerel gösterimini sürdürür.
- Yapılandırma JSON alanları JSONB olur. Kaynak kanıtları JSON payload'a dönüştürülmez; tipli ilişkisel kayıtlar korunur.
- SNMP metinlerinde PostgreSQL'in kabul etmediği NUL karakteri silinmez; görünür `\u0000` biçimine dönüştürülür. Aynı dönüşüm çalışma zamanı bağlamalarında uygulanır. Kaynak MariaDB ve korumalı yedeği özgün karakterleri korur. Doğrulama, bu açık dönüşümden sonraki bütün sütunları karşılaştırır.
- PostgreSQL dış birleşimlerinde satır kilidi yalnız ana modele `FOR UPDATE OF ...` uygulanır. VRF ve patch düzenlemelerinde transaction advisory lock kullanılır; kilit için başka menünün genel durum tablosuna yazılmaz.
- SQLSTATE `40001`, `40P01`, `55P03` ve geçici bağlantı hataları güvenli işlem yeniden deneme/çatışma yanıtlarına çevrilir. Cihaz komutu otomatik olarak tekrar oynatılmaz.

## Migration

PostgreSQL zinciri `backend/pg_migrations` altındadır. `20261106_01.sql`, başlangıcın dondurulmuş DDL'idir; gelecekte model değişse de tarihsel başlangıç değişmez. MariaDB migration zinciri PostgreSQL'e uygulanmaz.

```bash
alembic -c backend/postgresql.ini upgrade head
```

Uygulama başlamadan migration ve boş kurulum başlangıç kayıtları tamamlanır. Supervisor süreçlerine geçerken migration URL'si ortamdan kaldırılır. Çalışma zamanı hesabının yalnız menü şemalarında DML yetkisi vardır; şema oluşturma, DROP/ALTER ve Alembic sürüm yazma yetkisi yoktur.

## Tutarlı aktarım

1. Aktif firmware değişikliği olmadığını doğrula. Çalışan image revision'ını, ortam dosyasını ve kaynak SQL envanterini kaydet.
2. Canlı sisteme dokunmadan mevcut MariaDB'nin read-only tutarlı snapshot'ını ayrı PostgreSQL prova veritabanına aktar. Ağ worker/zamanlayıcıları başlatmadan 35 menüyü tarayıcıdan denetle.
3. Canlı geçişte API, worker, zamanlayıcı, etkileşimli test, firmware ve SSH süreçlerini durdur. Redis kalıcı volume'unu koru. Kaynak veritabanının korumalı yedeğini al.
4. Hedefin yalnız boş NETRIX tablolarından oluştuğunu doğrula. Aktarımı migration hesabıyla tek PostgreSQL transaction'ında yürüt:

```bash
python -m netrix.pg_transfer --confirm-target netrix --report /protected/transfer-report.json
```

`NETRIX_SOURCE_DATABASE_URL` kaynak MariaDB URL'sidir; komut satırı argümanı veya log değildir. Kaynak transaction read-only'dir. Hedefte önceden veri varsa aktarım hiçbir satırı değiştirmeden durur. 75 tablonun kolon envanteri doğrulanır; kimlikler ve şifreli değerler korunur. Dairesel FK'ler yalnız aktarım transaction'ında ertelenir ve commit öncesinde tekrar doğrulanır.

5. Her tablonun satır sayısını ve bütün kolonlarını kapsayan SHA-256 özetini karşılaştır. MariaDB/PostgreSQL sıralama farkları için satır hash'lerinin çoklu kümesi kullanılır; tekrarların sayısı kaybolmaz. Uyuşmazlık bütün transaction'ı geri alır. Rapor sır veya ham kayıt içermez.
6. Çalışma zamanı hesabının menü şemalarındaki yetkilerini ver, Alembic tablo yazımını kaldır. `.env` içindeki bağlantıları VIP PostgreSQL'e geçir; aynı doğrulanmış Git commit'inin image'ını başlat.
7. Container readiness/heartbeat'lerini, PostgreSQL oturumlarını ve HTTPS üzerinden 35 menüyü kontrol et. Cihaz/port MAC'i, VLAN'lar ve şifreli yedek okunabilirliğini doğrula. Test için yeni gerçek ağ taraması başlatma.

## Geri dönüş

Kaynak MariaDB silinmez. Geçiş öncesi image, `.env` ve SQL yedeği korunur. PostgreSQL'e geçilmeden hata olursa eski süreçler yeniden başlatılır. PostgreSQL canlı yazma kabul ettikten sonra kaynak MariaDB'ye doğrudan dönülmez: yeni işlemler ayrıca uzlaştırılmadan geri dönüş veri kaybettirir. Bu nedenle kesintiden önce prova ve içerik doğrulaması zorunludur.

## Test ve yedek

Varsayılan testler şemaları SQLite üzerinde tek ad alanına çevirir; çapraz FK'ler testlerde de korunur. PostgreSQL testleri yalnız açıkça verilen `NETRIX_TEST_DATABASE_URL` ile `*_test` isimli ayrı veritabanına erişir; fixture tüm test tablolarını sıfırlar. Cihaz/VMware/DHCP/DNS ağ erişimi kapalı kalır.

`python3 scripts/backup.py --output backups/netrix-TARIH.sql` PostgreSQL 18 `pg_dump` kullanır. Parola private pgpass dosyasından gelir; SQL çıktısı 0600'dür. Geri yükleme bakımda ve migration hesabıyla yapılır; çalışma zamanı hesabına DDL yetkisi verilmez. Şifreleme anahtarı veritabanından ayrı korunur.

Resmi başvurular: [PostgreSQL şemaları](https://www.postgresql.org/docs/current/ddl-schemas.html), [SQLAlchemy Psycopg](https://docs.sqlalchemy.org/en/20/dialects/postgresql.html#module-sqlalchemy.dialects.postgresql.psycopg).

## Mevcut test sapmaları

Geçiş öncesi `4179dd2` sürümü ayrı bir checkout'ta doğrulandı. İki `test_ipam_explicit_scope.py::test_manual_vlan_targets_only_its_ips_and_publishes_before_other_ip_finishes` çeşidi canlı probe beklentisinde zaman aşımına uğruyor. `test_ipam_host_connections.py` dosyasında da 12 kanıt/güncellik testi mevcut sürümde başarısız oluyor. Ayrıca `test_ipam_ssh_peer.py` içindeki `wrong_ip` çeşidi de eski sürümde aynı şekilde başarısızdır. Toplam 15 önceden mevcut test hatası vardır. Bunlar eski sürümle aynı sonuçlardır; PostgreSQL taşımasının oluşturduğu hatalar olarak değerlendirilmez ve başarılı raporlanmaz.

Bu geçiş IPAM kaynak eşleştirme algoritmasını değiştirmez. Migration, içerik eşitliği, PostgreSQL API testleri ve web doğrulamaları ayrıca yürütülür. Geniş regresyondaki başarısızlıklar eski sürümle tek tek karşılaştırılır.
