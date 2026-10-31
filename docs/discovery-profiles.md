# Ağ keşfi: SNMP profilleri ve kurum/lokasyon

Ağ Keşfi → Yeni kayıt / Kaydı düzenle formunda birden fazla SNMPv3 veya SNMPv2c profili seçilir. En az bir, en fazla 16 profil kabul edilir. Seçim sırası profillerin yanında gösterilir; sırayı değiştirmek için profilin seçimini kaldırıp yeniden seçin. SSH ve REST profilleri bu listede yer almaz.

Her hedef için profiller sırayla denenir. Ağ, kimlik doğrulama veya zaman aşımı hatasında sonraki profile geçilir; ilk başarılı okumadan sonra diğer profiller denenmez. Profil başına üst sınır 180 saniyedir, hedef eşzamanlılığı dört olarak korunur. Sonuçlar hedef sayısına göre sayılır; her profil denemesi ayrı hedef sayılmaz. Başarılı profil yeni cihazın SNMP profili olur. Mevcut cihazın kapsam dışındaki elle yönetilen profili korunur. İptal, kapsamın kapatılması, profil kaldırılması veya sorgu sırasında sır değişimi eski sonuçların kaydedilmesini engeller.

Önce ortak lokasyon kataloğundan Kurum seçilir. Lokasyon listesi yalnızca bu kuruma ait ana ve alt lokasyonları içerir; kurum değişince lokasyon seçimi temizlenir. Kurum zorunludur, lokasyon isteğe bağlıdır. Yanlış kuruma ait lokasyon API'de de reddedilir. Bir lokasyon başka kuruma taşınmadan önce onu kullanan keşif kapsamları güncellenmelidir.

Kayıt işlemi doğrudan tarama işi oluşturmaz. Otomatik tarama için mevcut zamanlayıcı ve en az 300 saniyelik aralık kullanılır; 0 yalnızca elle tetikleme anlamına gelir.

## API ve geçiş

`POST /api/v1/scopes` ve `PUT /api/v1/scopes/{id}` sıralı `credential_ids` dizisi ve `institution_id` kabul eder. Aynı profil yinelenirse ilk konumu korunur. Yanıtta eski istemciler için `credential_id` ilk profili göstermeye devam eder. Eski, yalnızca `credential_id` gönderen istemciler tek profil ile çalışır; iki alan birlikte gönderildiğinde `credential_ids` belirleyicidir. Kurumu göndermeyen eski istemcilerde seçilmiş lokasyonun kurumu kullanılır. Önceden lokasyonsuz kaydedilmiş kapsamlar korunur.

Alembic `20261031_16`, mevcut profilleri sıralı ilişki tablosuna taşır ve mevcut lokasyonun kurumunu kapsama aktarır. Yeni kurum veya erişim profili üretmez; zamanlama ve etkinlik değerlerini değiştirmez. Kullanılan ikincil profillerin silinmesi FK ile engellenir. Bir kapsamda birden fazla profil veya lokasyondan çıkarılamayan kurum ataması varsa veri kaybettirecek downgrade reddedilir.

## Doğrulama

- `pytest -q tests/test_discovery_profiles.py tests/test_snmpv2c.py tests/test_engines.py`: sahte istemcilerle profil sırası, hata/zaman aşımı sonrası geçiş, doğru protokol ve profil kaydı, iptal/erişim değişimi, eski API uyumu, kurum/lokasyon doğrulaması. Testlerde gerçek ağ erişimi engellenir.
- `scripts/discovery_profiles_migration_check.py`: yalnızca atılabilir MariaDB `netrix_test` üzerinde eski kayıt geçişi, FK/tekillik, kullanılan profilin silinme engeli, downgrade koruması ve cascade.
- `scripts/discovery_profiles_fixture.py` ile `scripts/discovery_profiles_browser_check.py`: 8232 portunda geçici yerel veri, oluşturma/düzenleme, kurum değişimi, profil seçimi/sırası, kaydetmede iş oluşmaması; 1440×1000, 375×812, 812×375 ve açık/koyu temada hizalama, erişilebilirlik, taşma ve alt eylem düğmelerine erişim.
