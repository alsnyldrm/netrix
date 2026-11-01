# Konfigürasyon, base config ve onay

Konfigürasyon → Cihaz Konfigürasyonları cihaz başına dosyaları gösterir. İlk geçerli dosya otomatik base config olur ve ayrı renkle işaretlenir. Kullanıcı herhangi bir geçerli dosyayı Base config yap ile seçebilir. Base dosyası saklama sınırından korunur ve başka base seçilmeden silinemez.

Değişenler her cihazın yalnızca son dosyasını seçili base config ile karşılaştırır. `conf_file_ver`, FortiOS sürüm/build üstbilgileri ve `!Version AOS-CX ...` satırları gerçek ayar farkı sayılmaz. Dosyanın başındaki `show running-config` gibi okuma komutu yankıları ve çıktı başlıkları da ayıklanır; konfigürasyon içindeki alıntılı metinler korunur. Komutlar, değerler ve gizli değer değişiklikleri karşılaştırmaya dahildir; ekranda sırlar maskelenir. Alıntılı banner/çok satırlı değerlerin içindeki benzer metinler atılmaz.

Onayla, incelenen son dosyanın normalleştirilmiş hash’ini kullanıcı/zaman bilgisiyle saklar ve aynı konfigürasyon farkını bekleyen listeden kaldırır. Base config kendiliğinden değişmez. Başka bir gerçek ayar değişikliği yeni onay bekler. İncelenen dosya artık en son dosya değilse onay reddedilir. Menü rozeti onay bekleyen cihaz sayısıdır.

Yedek al yanındaki Karşılaştır iki kayıtlı dosyayı sol/sağ pencerede açar. Ayrı Karşılaştır ekranı 2–4 farklı cihaz ve her cihazdan bir dosya seçtirir. Metin panelleri değişen satırları işaretler; birleşik fark görünümü eklenen/kaldırılan satırları da gösterir. İşlem cihazlara bağlanmaz, kayıtlı dosyaları kullanır.
