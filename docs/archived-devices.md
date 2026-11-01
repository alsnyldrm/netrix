# Arşivlenmiş cihazlar

Envanter → Arşivlenmiş cihazlar, aktif cihaz listesinden kaldırılan kayıtları tutar. Normal cihaz listesindeki Sil işlemi arşivler; fiziksel kayıt ve geçmiş korunur.

Yönetici, satırdaki **Geri yükle** veya **Kalıcı sil** düğmesini kullanabilir. Seçim çubuğundaki **Toplu geri yükle** ve **Kalıcı sil** sürekli görünür; kutucuklardan cihaz seçilene kadar pasiftir. Sayfa başlığındaki kutu mevcut sayfayı seçer; işlem en fazla 100 seçili kayıt içindir. Her iki işlem onay penceresinden uygulanır.

Geri yükleme tekli/toplu olarak aynı kayıt kimliğini ve geçmişi korur. Cihaz Bakımda durumuna döner, otomatik yedekleme başlamaz.

Kalıcı silme `POST /api/v1/inventory/devices/bulk`, `action: purge` ile yalnızca yöneticiye ve yalnızca arşivlenmiş cihazlara açıktır. Seçimde aktif/eksik kayıt veya çalışan cihaz işi varsa tüm istek reddedilir; kısmi silme olmaz. Bekleyen cihaz işleri iptal edilir. Cihaz, portları, konfigürasyon yedekleri (base dahil), keşif gözlemleri, alarm kayıtları, bağlı komşuluklar ve kabin yerleşimi silinir. Bu işlem geri alınamaz. Önce onay metni gösterilir; sayfayı açmak veya seçim yapmak silme başlatmaz.

VLAN/IPAM adresleri, ortak erişim profilleri, lokasyonlar ve yedek grupları silinmez. IPAM'in cihaz/port bağlantıları boşaltılır. Görev ve denetim geçmişi tutulur; olaylar cihaz adı/IP özetiyle cihazdan ayrılır. Etkin keşif aynı cihazı tekrar bulursa yeniden envanter kaydı oluşturabilir.

Doğrulamalar: `tests/test_archive_purge.py`, `tests/test_inventory_management.py`, geçici MariaDB üzerinde `scripts/archive_purge_check.py`, masaüstü/mobil Playwright için `scripts/archive_actions_browser_check.py`. Bu testler üretim cihazlarını silmez ve ağa cihaz sorgusu yapmaz.
