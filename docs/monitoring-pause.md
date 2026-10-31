# İzleme görevlerini geçici durdurma

Sunucu ortamında `NETRIX_MONITOR_JOBS_ENABLED=false` ayarı, yalnızca `monitor` türündeki işleri durdurur. Ayar değişikliği sonrasında uygulama container'ı yeniden oluşturulmalıdır. Varsayılan değer `true` olarak korunmuştur.

- API ve ortak kuyruk servisi yeni izleme işini 409 ve açıklayıcı mesajla reddeder. IPAM keşfi aynı servisi kullandığı için izleme işi oluşturamaz; kendi keşif işlemi devam eder.
- Zamanlayıcı izleme işi ve izleme kesintisine bağlı `no_data` değerlendirmesi üretmez.
- Worker/zamanlayıcı bekleyen izleme işlerini iptal eder; çalışanlar için iptal ister. Worker önceden alınmış bir izleme işini de cihaz sorgusu yapmadan iptal eder.
- Cihazlardaki `monitoring_enabled`, izleme aralığı ve geçmiş ölçümler değiştirilmez. Tamamlanmış görev geçmişi korunur. Keşif, yedekleme ve diğer görev türleri bu ayardan etkilenmez.

Tekrar açmak için ortam değerini `true` yapıp container'ı yeniden oluşturun. İptal edilmiş işler otomatik canlandırılmaz; yeni işler mevcut cihaz zamanlamaları veya kullanıcı tetiklemesiyle oluşur.

`tests/test_monitor_pause.py`, API/zamanlayıcı/IPAM üreticilerini, bekleyen ve çalışan iş iptalini, sorgudan önce worker korumasını, geçmişin ve cihaz tercihlerinin korunmasını ve yeniden açılmayı sahte istemcilerle doğrular. Testler gerçek cihazlara erişmez.
