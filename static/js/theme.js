// Tema yönetimi
(function() {
    // Sayfa yüklenmeden önce tema tercihini uygula
    const savedTheme = localStorage.getItem('theme') || 'light';
    document.documentElement.setAttribute('data-bs-theme', savedTheme);
    
    // Geçiş animasyonunu devre dışı bırak
    document.documentElement.style.transition = 'none';
    
    // Sayfa yüklendiğinde tema değiştirme butonunu ayarla
    document.addEventListener('DOMContentLoaded', () => {
        const themeSwitch = document.getElementById('themeSwitch');
        if (themeSwitch) {
            themeSwitch.checked = savedTheme === 'dark';
            
            // Tema değiştirme olayını dinle
            themeSwitch.addEventListener('change', () => {
                const newTheme = themeSwitch.checked ? 'dark' : 'light';
                document.documentElement.setAttribute('data-bs-theme', newTheme);
                localStorage.setItem('theme', newTheme);
            });
        }
        
        // Geçiş animasyonunu tekrar etkinleştir
        setTimeout(() => {
            document.documentElement.style.transition = '';
        }, 0);
    });
})(); 