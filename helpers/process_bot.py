from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import Select
import pandas as pd
import time
import os
import sys
import traceback


class ProcessBot:
    def __init__(self, excel_path):
        try:
            # Chrome ayarlarını yapılandır
            chrome_options = Options()
            chrome_options.add_argument("--start-maximized")
            chrome_options.add_argument("--disable-notifications")
            
            # Chrome driver'ı otomatik yönet
            service = Service()  # Boş Service objesi oluştur
            self.driver = webdriver.Chrome(options=chrome_options)  # Selenium 4 otomatik driver bulur
            self.wait = WebDriverWait(self.driver, 20)  # Bekleme süresini artırdık
            self.excel_path = excel_path
            
            print("Chrome başlatıldı")
        except Exception as e:
            print("Chrome driver başlatma hatası: {}".format(str(e)))
            sys.exit(1)
        
    def login(self, url="http://127.0.0.1:5001/"):
        """Web arayüzüne giriş yap"""
        try:
            self.driver.get(url)
            print("Web arayüzüne bağlanıldı: {}".format(url))
            
            # Ana sayfanın yüklenmesini bekle
            self.wait.until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
            time.sleep(2)  # Sayfa tam yüklensin diye ekstra bekleme
            
        except Exception as e:
            print("Web arayüzüne bağlanma hatası: {}".format(str(e)))
            self.driver.quit()
            sys.exit(1)
        
    def create_process(self, process_name, description):
        """Yeni süreç oluştur"""
        try:
            print("Yeni süreç oluşturma sayfası açılıyor...")
            
            # Yeni süreç sayfasına git
            self.driver.get(self.driver.current_url + "/process/new")
            time.sleep(2)
            
            # Form elementlerini bul
            name_input = self.wait.until(
                EC.presence_of_element_located((By.NAME, "name"))
            )
            name_input.send_keys(process_name)
            
            desc_input = self.driver.find_element(By.NAME, "description")
            desc_input.send_keys(description)
            
            # Formu gönder
            submit_btn = self.driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
            submit_btn.click()
            
            # Süreç detay sayfasının yüklenmesini bekle
            time.sleep(2)
            print("Süreç başarıyla oluşturuldu: {}".format(process_name))
            
        except Exception as e:
            print("Süreç oluşturma hatası: {}".format(str(e)))
            print("Hata detayı:")
            traceback.print_exc()
            raise
        
    def add_step(self, name, responsible, description, parent_step=None):
        """Sürece yeni adım ekle"""
        try:
            print("Yeni adım ekleniyor: {}".format(name))
            
            if parent_step:
                # Alt adım ekleme
                print(f"Alt adım ekleniyor: {name} (Ana adım: {parent_step})")
                
                try:
                    # Ana adımın sayfasına git
                    # Önce süreç sayfasındaki ana adımı bul
                    print(f"Ana adım ({parent_step}) aranıyor...")
                    
                    # Tüm adım linklerini bul ve içeriklerini kontrol et
                    step_links = self.wait.until(
                        EC.presence_of_all_elements_located((By.CSS_SELECTOR, "table tbody tr td a[href*='/step/']"))
                    )
                    
                    main_step_url = None
                    for link in step_links:
                        # Link'in bulunduğu satırdaki adım numarasını kontrol et
                        parent_td = link.find_element(By.XPATH, "../..")  # td'nin parent'ına (tr) git
                        step_no = parent_td.find_element(By.TAG_NAME, "td").text.strip()
                        print(f"Bulunan adım no: {step_no}")
                        
                        if step_no == parent_step:
                            main_step_url = link.get_attribute('href')
                            print(f"Ana adım URL'si bulundu: {main_step_url}")
                            break
                    
                    if not main_step_url:
                        raise Exception(f"Ana adım ({parent_step}) bulunamadı!")
                    
                    # Ana adım sayfasına git
                    self.driver.get(main_step_url)
                    time.sleep(2)
                    
                    # Sayfanın yüklenmesini bekle
                    self.wait.until(EC.presence_of_element_located((By.TAG_NAME, "table")))
                    
                    # Alt Adım butonunu bul
                    print("Alt Adım butonu aranıyor...")
                    buttons = self.wait.until(
                        EC.presence_of_all_elements_located((By.CSS_SELECTOR, "a.btn.btn-outline-primary"))
                    )
                    
                    alt_adim_btn = None
                    for btn in buttons:
                        if "Alt Adım" in btn.text:
                            alt_adim_btn = btn
                            print("Alt Adım butonu bulundu!")
                            break
                    
                    if alt_adim_btn:
                        # JavaScript ile tıklama işlemini gerçekleştir
                        print("Butona tıklanıyor...")
                        self.driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", alt_adim_btn)
                        time.sleep(1)
                        self.driver.execute_script("arguments[0].click();", alt_adim_btn)
                        time.sleep(2)
                    else:
                        raise Exception("Alt Adım butonu bulunamadı!")
                        
                except Exception as e:
                    print(f"Alt adım ekleme hatası: {str(e)}")
                    raise
            else:
                # Ana adım ekleme
                print(f"Ana adım ekleniyor: {name}")
                # Yeni adım sayfasına git
                self.driver.get(self.driver.current_url + "/step/new")
            
            time.sleep(2)
            
            # Form elementlerini doldur
            print("Form elementleri dolduruluyor...")
            name_input = self.wait.until(
                EC.presence_of_element_located((By.NAME, "name"))
            )
            name_input.send_keys(name)
            
            responsible_input = self.driver.find_element(By.NAME, "responsible")
            responsible_input.send_keys(responsible)
            
            desc_input = self.driver.find_element(By.NAME, "description")
            desc_input.send_keys(description)
            
            # Adım tipini seç
            type_select = Select(self.driver.find_element(By.NAME, "type"))
            type_select.select_by_value("main_step")
            
            # Formu gönder
            submit_btn = self.driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
            submit_btn.click()
            
            # Adımın eklenmesini bekle
            time.sleep(2)
            print("Adım başarıyla eklendi: {}".format(name))
            
        except Exception as e:
            print("Adım ekleme hatası: {}".format(str(e)))
            print("Hata detayı:")
            traceback.print_exc()
            raise
        
    def create_from_excel(self):
        """Excel dosyasından süreç ve adımları oluştur"""
        try:
            print("Excel dosyası okunuyor: {}".format(self.excel_path))
            try:
                # Header olmadan oku ve ilk satırı atla
                df = pd.read_excel("ProcessGuide_2503.xlsx",  engine='openpyxl', header=None, skiprows=1)
                print("Excel dosyası başarıyla okundu")
                print("Toplam {} satır bulundu".format(len(df)))
                
                # İlk birkaç satırı göster
                print("\nİlk 3 satır:")
                print(df.head(3))
                print("\nSütun sayısı:", len(df.columns))
                
            except Exception as e:
                print("Excel okuma hatası: {}".format(str(e)))
                print("Hata detayı:")
                traceback.print_exc()
                return
            
            # Süreç adı ve açıklaması
            process_name = "Ortalama Muallak"
            description = "Ortalama Muallak"
            
            # Süreci oluştur
            self.create_process(process_name, description)
            
            # Alt adımları sakla
            sub_steps = []  # [(parent_no, name, responsible, description), ...]
            
            # Her satır için
            for index, row in df.iterrows():
                try:
                    # Sütunları indeks numaralarıyla oku
                    step_no = str(row.iloc[0]).strip()
                    name = str(row.iloc[1]).strip()
                    responsible = str(row.iloc[2]).strip()
                    description = str(row.iloc[3]).strip()
                    
                    # Boş satırları atla
                    if pd.isna(step_no) or pd.isna(name):
                        continue
                    
                    print(f"\nİşlenen satır {index + 1}:")
                    print(f"  Adım No: {step_no}")
                    print(f"  Adım Adı: {name}")
                    print(f"  Sorumlu: {responsible}")
                    print(f"  Açıklama: {description}")
                    
                    # Ana adım mı kontrol et
                    if '.' not in str(step_no) or str(step_no).endswith('.0'):  # Ana adım veya x.0 formatında
                        print("Ana adım ekleniyor: {}".format(name))
                        self.add_step(name, responsible, description)
                    else:  # Alt adım
                        # Parent adımı nokta sayısına göre belirle
                        parts = step_no.split('.')
                        if len(parts) == 2 and not parts[1] == '0':  # Örnek: 1.1
                            parent_no = parts[0]  # Ana adımın altına ekle
                        else:  # Örnek: 1.1.1
                            parent_no = '.'.join(parts[:-1])  # Son parçayı çıkar
                        
                        sub_steps.append((parent_no, name, responsible, description))
                        print(f"Alt adım kaydedildi: {step_no} (Parent adım: {parent_no})")
                except Exception as e:
                    print("Satır {} işlenirken hata oluştu: {}".format(index + 1, str(e)))
                    continue
            
            # Tüm ana adımlar eklendikten sonra alt adımları JavaScript ile ekle
            print("\nAlt adımlar ekleniyor...")
            time.sleep(2)  # Ana adımların tam oluşması için bekle
            
            for parent_no, name, responsible, description in sub_steps:
                try:
                    print(f"\nAlt adım ekleniyor: {name} (Ana adım: {parent_no})")                    
                    # JavaScript ile alt adım ekleme
                    js_code = """
                        // Tablo satırlarını bul
                        var rows = document.querySelectorAll('table tbody tr');
                        var parentStepNo = arguments[0];
                        var found = false;

                        // Her satırı kontrol et
                        for (let row of rows) {
                            // Satırdaki ilk hücreyi (step no) kontrol et
                            let stepCell = row.querySelector('td');
                            if (stepCell && stepCell.textContent.trim() === parentStepNo) {
                                // Bu satırda Alt Adım butonunu bul
                                let altAdimBtn = row.querySelector('a.btn.btn-outline-primary');
                                if (altAdimBtn) {
                                    console.log("Buton bulundu!");
                                    altAdimBtn.scrollIntoView({behavior: "smooth", block: "center"});
                                    setTimeout(() => altAdimBtn.click(), 500);
                                    found = true;
                                    break;
                                }
                            }
                        }
                        return found;
                    """
                    
                    # Alt Adım butonuna tıkla
                    button_found = self.driver.execute_script(js_code, parent_no)
                    if not button_found:
                        raise Exception(f"Alt Adım butonu bulunamadı (Ana adım: {parent_no})")
                    
                    time.sleep(2)  # Yeni sayfa yüklensin
                    
                    # Form elementlerini doldur
                    name_input = self.wait.until(
                        EC.presence_of_element_located((By.NAME, "name"))
                    )
                    name_input.send_keys(name)
                    
                    responsible_input = self.driver.find_element(By.NAME, "responsible")
                    responsible_input.send_keys(responsible)
                    
                    desc_input = self.driver.find_element(By.NAME, "description")
                    desc_input.send_keys(description)
                    
                    # Adım tipini seç
                    type_select = Select(self.driver.find_element(By.NAME, "type"))
                    type_select.select_by_value("main_step")  # Alt adımlar için de main_step seç
                    
                    # Formu gönder
                    submit_btn = self.driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
                    submit_btn.click()
                    
                    time.sleep(2)  # İşlem tamamlansın
                    
                    # Ana süreç sayfasına dön
                    print("Ana süreç sayfasına dönülüyor...")
                    self.driver.get(self.driver.current_url.split('/step/')[0])  # Ana süreç URL'sine git
                    
                    # Sayfanın yüklenmesini bekle
                    self.wait.until(EC.presence_of_element_located((By.TAG_NAME, "table")))
                    time.sleep(2)  # Extra bekleme
                    
                except Exception as e:
                    print(f"Alt adım eklenirken hata oluştu: {str(e)}")
                    # Hata durumunda da ana sayfaya dön
                    try:
                        self.driver.get(self.driver.current_url.split('/step/')[0])
                        time.sleep(2)
                    except:
                        pass
                    continue
            
            print("Süreç ve tüm adımlar başarıyla oluşturuldu!")
            
        except Exception as e:
            print("Hata oluştu: {}".format(str(e)))
            print("Hata detayı:")
            traceback.print_exc()
        finally:
            print("Tarayıcı kapatılıyor...")
            self.driver.quit()

def main():
    try:
        # Excel dosyasının yolunu belirt
        excel_path = "ProcessGuide_2025.xlsx"
        
        if not os.path.exists(excel_path):
            print("Hata: Excel dosyası bulunamadı: {}".format(excel_path))
            sys.exit(1)
        
        print("Bot başlatılıyor...")
        bot = ProcessBot(excel_path)
        bot.login()
        bot.create_from_excel()
    except Exception as e:
        print("Beklenmeyen bir hata oluştu: {}".format(str(e)))
        print("Hata detayı:")
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main() 