# Konfigürasyon, base config ve onay

Konfigürasyon → Cihaz Konfigürasyonları cihaz başına dosyaları gösterir. İlk geçerli dosya otomatik base config olur ve ayrı renkle işaretlenir. Kullanıcı herhangi bir geçerli dosyayı Base config yap ile seçebilir. Base dosyası saklama sınırından korunur ve başka base seçilmeden silinemez.

Değişenler her cihazın yalnızca son dosyasını seçili base config ile karşılaştırır. `conf_file_ver`, FortiOS sürüm/build üstbilgileri ve `!Version AOS-CX ...` satırları gerçek ayar farkı sayılmaz. Dosyanın başındaki `show running-config` gibi okuma komutu yankıları ve çıktı başlıkları da ayıklanır; konfigürasyon içindeki alıntılı metinler korunur. Komutlar, değerler ve gizli değer değişiklikleri karşılaştırmaya dahildir; ekranda sırlar maskelenir. Alıntılı banner/çok satırlı değerlerin içindeki benzer metinler atılmaz.

Onayla, incelenen son dosyanın normalleştirilmiş hash’ini kullanıcı/zaman bilgisiyle saklar ve aynı konfigürasyon farkını bekleyen listeden kaldırır. Base config kendiliğinden değişmez. Başka bir gerçek ayar değişikliği yeni onay bekler. İncelenen dosya artık en son dosya değilse onay reddedilir. Menü rozeti onay bekleyen cihaz sayısıdır.

Bir cihazın içine girildiğinde Yedek al yanındaki Karşılaştır, seçili cihazın iki kayıtlı dosyasını sol/sağ pencerede açar. Cihaz listesinde ve cihaz adının yanında Karşılaştır düğmesi bulunmaz; genel “Cihaz konfigürasyonlarını karşılaştır” penceresi kaldırılmıştır. Ayrı Karşılaştır ekranı 2–4 farklı cihaz ve her cihazdan bir dosya seçtirir. Metin panelleri değişen satırları işaretler; birleşik fark görünümü eklenen/kaldırılan satırları da gösterir. İşlem cihazlara bağlanmaz, kayıtlı dosyaları kullanır.

Düğme yerleşimi (1 Kasım 2026): cihaz bağlamı sayfa başlığına aktarılır; karşılaştırma seçili cihaz ile açılır. Listeye dönüşte ve ekran değişiminde bu bağlam temizlenir. Mobilde Yedek al ve Karşılaştır aynı satırda eşit genişlikte kalır. `scripts/configuration_actions_browser_check.py`, masaüstü/mobil ve açık/koyu temada 12 görünümü; doğru cihazın iki dosyasını karşılaştırmayı, klavye/fokus dönüşünü, listeye dönmeyi, cihaz değiştirmeyi, hizalama ve Axe kontrollerini doğrular. Gerçek cihaz sorgusu yapılmaz.

Cihaz listesinde yönetici satır sonundaki çöp kutusuyla tek cihazın, seçim kutularıyla bir veya daha fazla cihazın yedek geçmişini silebilir. Onaydan sonra seçilen geçmişlerin tamamı ve base config seçimi temizlenir; cihaz, envanter ilişkileri, yedekleme ayarları ve görev geçmişi korunur. İlk sonraki geçerli yedek yeni base config olur. Çalışan karşılaştırma veya firmware geçmişi seçilen bir yedeği kullanıyorsa bütün silme işlemi değişiklik yapmadan reddedilir. Tek dosya silmede base config koruması devam eder.

Cihazın yedek geçmişinde yönetici, base config dışındaki dosyaları tek tek veya sayfa başlığındaki seçim kutusuyla seçip **Seçilen yedekleri sil** eylemini kullanabilir. Yalnız seçili dosyalar silinir. Başka cihaza ait, base config olan veya karşılaştırma/firmware için kullanılan bir dosya varsa istek hiçbir dosyayı silmez.

**Yedekleme ayarları → Seçilenleri yedekle**, seçili uygun cihazlar için mevcut SSH yedekleme görevini sıraya alır. Aynı cihazın sırada veya çalışan bir görevi varsa onu kullanır. Uygun olmayan cihazlar nedenleriyle gösterilir; mevcut zamanlama ve saklama ayarları değişmez. İlerleme Görev merkezi'nden izlenir.
