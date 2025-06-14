import shutil
import subprocess
import os
import pandas as pd
import sqlite3
import json
from datetime import datetime
import platform
import logging
import numpy as np

logger = logging.getLogger(__name__)

IS_WINDOWS = platform.system() == 'Windows'

if IS_WINDOWS:
    import win32com.client
    import pythoncom

class ProcessExecutor:
    _instance = None
    _db_path = None  
    _oracle_config = {
        'username': None,
        'password': None,
        'dsn': None
    }
    
    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    @classmethod
    def set_db_path(cls, db_path):
        """Veritabanı yolunu ayarla"""
        cls._db_path = db_path

    @classmethod
    def set_oracle_config(cls, username, password, dsn):
        cls._oracle_config = {
            'username': username,
            'password': password,
            'dsn': dsn
        }


    @classmethod
    def _check_db_process_status(cls):
        """Veritabanından süreç durumunu kontrol et"""
        if not cls._db_path:
            return False
        
        try:
            conn = sqlite3.connect(cls._db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM process WHERE is_started = 1")
            count = cursor.fetchone()[0]
            conn.close()
            return count > 0
        except Exception:
            return False

    @staticmethod
    def start_process():
        """Süreci başlatır"""
        return {
            'success': True,
            'output': 'Süreç başlatıldı',
            'error': None
        }

    @staticmethod
    def stop_process():
        """Süreci durdurur"""
        return {
            'success': True,
            'output': 'Süreç durduruldu',
            'error': None
        }

    @classmethod
    def check_process_started(cls):
        """Sürecin başlatılıp başlatılmadığını kontrol eder"""
        if not cls._check_db_process_status():
            return {
                'success': False,
                'output': None,
                'error': 'Süreç başlatılmadan adımlar çalıştırılamaz. Lütfen önce süreci başlatın.'
            }
        return None

    @staticmethod
    def send_mail(variables_list):
        if not IS_WINDOWS:
            return {
                'success': False,
                'output': None,
                'error': 'Mail gönderme özelliği sadece Windows işletim sisteminde desteklenmektedir.'
            }

        # Süreç kontrolü
        check_result = ProcessExecutor.check_process_started()
        if check_result:
            return check_result

        results = []
        if not isinstance(variables_list, list):
            variables_list = [variables_list]

        for variables in variables_list:
            try:
                pythoncom.CoInitialize()
                # Mail konfigürasyonunu kontrol et
                if not variables:
                    raise Exception('Mail konfigürasyonu bulunamadı')
                if not variables.get('to'):
                    raise Exception('En az bir alıcı belirtilmeli')
                if not variables.get('subject'):
                    raise Exception('Mail konusu belirtilmeli')
                if not variables.get('body'):
                    raise Exception('Mail içeriği belirtilmeli')
                if not variables.get('active', False):
                    results.append({
                        'success': True,
                        'output': 'Mail gönderimi pasif durumda',
                        'error': None
                    })
                    continue
                try:
                    outlook = win32com.client.Dispatch('Outlook.Application')
                    mail = outlook.CreateItem(0)
                    if isinstance(variables['to'], list):
                        mail.To = '; '.join(variables['to'])
                    else:
                        mail.To = variables['to']
                    if variables.get('cc'):
                        if isinstance(variables['cc'], list):
                            mail.CC = '; '.join(variables['cc'])
                        else:
                            mail.CC = variables['cc']
                    mail.Subject = variables['subject']
                    mail.Body = variables['body']
                    mail.Send()
                    results.append({
                        'success': True,
                        'output': 'Mail başarıyla gönderildi',
                        'error': None
                    })
                except Exception as e:
                    results.append({
                        'success': False,
                        'output': None,
                        'error': f'Mail gönderilirken hata oluştu: {str(e)}'
                    })
            except Exception as e:
                results.append({
                    'success': False,
                    'output': None,
                    'error': str(e)
                })
            finally:
                if IS_WINDOWS:
                    pythoncom.CoUninitialize()
        # Eğer hepsi başarılıysa success True, biri bile başarısızsa False
        overall_success = all(r['success'] for r in results)
        return {
            'success': overall_success,
            'results': results,
            'output': '\n'.join([r['output'] or '' for r in results]),
            'error': '\n'.join([r['error'] or '' for r in results if r['error']]) if not overall_success else None
        }

    @staticmethod
    def execute_mail_check(start_date=None):
        if not IS_WINDOWS:
            return {
                'success': False,
                'output': None,
                'error': 'Mail kontrol özelliği sadece Windows işletim sisteminde desteklenmektedir.'
            }

        check_result = ProcessExecutor.check_process_started()
        if check_result:
            return check_result

        try:
            pythoncom.CoInitialize()
            outlook = win32com.client.Dispatch('Outlook.Application')
            namespace = outlook.GetNamespace('MAPI')
            inbox = namespace.GetDefaultFolder(6)  # 6 = Gelen Kutusu

            messages = inbox.Items
            messages.Sort('[ReceivedTime]', True)  # En yeni mailler başta olacak

            mails = []
            count = messages.Count if hasattr(messages, 'Count') else 0
            print(f"[DEBUG] messages.Count: {count}")

            # Son 30 maili topla, Python'da filtrele
            for i in range(1, min(count, 30) + 1):
                try:
                    message = messages.Item(i)
                    received_time = message.ReceivedTime
                    if start_date:
                        # received_time offset-aware ise, tzinfo'sunu sil
                        if hasattr(received_time, 'tzinfo') and received_time.tzinfo is not None:
                            received_time = received_time.replace(tzinfo=None)
                        if received_time < start_date:
                            continue
                    mail_info = {
                        'subject': message.Subject,
                        'sender': message.SenderName,
                        'received': received_time.strftime('%Y-%m-%d %H:%M:%S'),
                        'body': message.Body[:200] + '...' if len(message.Body) > 200 else message.Body
                    }
                    print(f"[DEBUG][INBOX] Subject: {mail_info['subject']} | Sender: {mail_info['sender']} | Received: {mail_info['received']}")
                    mails.append(mail_info)
                    if len(mails) >= 10:
                        break
                except Exception as e:
                    print(f"[ERROR][MAIL_LOOP] {str(e)}")
                    continue

            return {'success': True, 'output': mails}
        except Exception as e:
            print(f"[ERROR][MAIL_CHECK] {str(e)}")
            return {'success': False, 'error': str(e)}
        finally:
            if IS_WINDOWS:
                pythoncom.CoUninitialize()

    @staticmethod
    def execute_python_script(file_path, output_dir=None, variables=None):
        # Süreç kontrolü
        check_result = ProcessExecutor.check_process_started()
        if check_result:
            return check_result
        var_list = []
        for variable in variables:
            var_list.append({"id": variable.name, "default_value": variable.default_value})
        variables = json.dumps(var_list)
        try:
            # Dosya yolundaki tırnak işaretlerini kaldır ve yolu normalize et
            file_path = file_path.strip('"').strip("'")
            file_path = os.path.normpath(file_path)

            # Çıktı dizinini ayarla
            env = os.environ.copy()
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
                env['OUTPUT_DIR'] = output_dir
                ProcessExecutor._files_before = set(os.listdir(output_dir))
            # Python scriptini çalıştır
            result = subprocess.run(['python', file_path],
                                capture_output=True,
                                text=True,
                                check=True,
                                input=variables,
                                env=env,
                                cwd=output_dir if output_dir else None)
            # Çıktı dosyasını kontrol et
            output_file = None
            moved_file_path = None
            if output_dir and hasattr(ProcessExecutor, '_files_before'):
                files_after = set(os.listdir(output_dir))
                new_files = files_after - ProcessExecutor._files_before
                if new_files:
                    output_file = list(new_files)[0]
                    # Dosyayı indirilenler klasörüne taşı
                    downloads_dir = os.path.join(os.environ['USERPROFILE'], 'Downloads')
                    os.makedirs(downloads_dir, exist_ok=True)
                    src_path = os.path.join(output_dir, output_file)
                    dst_path = os.path.join(downloads_dir, output_file)
                    shutil.move(src_path, dst_path)
                    moved_file_path = dst_path

            return {
                'success': True,
                'output': result.stdout,
                'error': result.stderr,
                'output_file': output_file,
                'moved_file_path': moved_file_path
            }
        except subprocess.CalledProcessError as e:
            return {
                'success': False,
                'output': e.stdout,
                'error': e.stderr
            }
        except Exception as e:
            return {
                'success': False,
                'output': None,
                'error': str(e)
            }

    @staticmethod
    def execute_sql_script(step):
        """SQL script adımını çalıştırır"""
        try:
            # SQL dosyasını oku
            with open(step.file_path, 'r', encoding='utf-8') as f:
                sql_content = f.read()

            # Değişkenleri kontrol et ve değerlerini yerleştir
            if step.variables:
                for variable in step.variables:
                    param_name = f"&{variable.name}"
                    if param_name in sql_content:
                        # Değişken tipine göre değeri dönüştür
                        value = variable.default_value
                        if variable.var_type == 'number':
                            # Sayısal değerler için tırnak kullanma
                            sql_content = sql_content.replace(param_name, value)
                        elif variable.var_type == 'date':
                            # Tarih değerleri için TO_DATE fonksiyonu kullan
                            sql_content = sql_content.replace(param_name, f"TO_DATE('{value}', 'YYYY-MM-DD')")
                        else:  # text
                            # Metin değerleri için tırnak kullan
                            sql_content = sql_content.replace(param_name, f"'{value}'")

            # Oracle bağlantısını oluştur
            import oracledb
            connection = oracledb.connect(
                user=ProcessExecutor._oracle_config['username'],
                password=ProcessExecutor._oracle_config['password'],
                dsn=ProcessExecutor._oracle_config['dsn']
            )
            cursor = connection.cursor()

            # SQL komutlarını ayır
            # Önce her satırı ayrı ayrı al
            lines = sql_content.split('\n')
            current_command = []
            commands = []
            
            for line in lines:
                # Satırı temizle
                line = line.strip()
                
                # Yorum satırlarını atla
                if line.startswith('--'):
                    continue
                    
                # Boş satırları atla
                if not line:
                    continue
                
                # Satırı mevcut komuta ekle
                current_command.append(line)
                
                # Eğer satır noktalı virgül ile bitiyorsa, komutu tamamla
                if line.rstrip().endswith(';'):
                    # Komutu birleştir ve noktalı virgülü kaldır
                    command = ' '.join(current_command).rstrip(';')
                    commands.append(command)
                    current_command = []

            # Eğer son komut noktalı virgül ile bitmiyorsa, onu da ekle
            if current_command:
                command = ' '.join(current_command).rstrip(';')
                commands.append(command)

            # Her komutu ayrı ayrı çalıştır
            results = []
            query_count = 1
            
            # Excel dosyasını hazırla
            import pandas as pd
            from datetime import datetime
            
            # SQL dosyasının adını al (uzantısız)
            sql_filename = os.path.splitext(os.path.basename(step.file_path))[0]
            excel_filename = f"{sql_filename}.xlsx"
            excel_path = os.path.join(os.environ['USERPROFILE'], 'Downloads', excel_filename)
            
            # Excel writer oluştur
            with pd.ExcelWriter(excel_path, engine='openpyxl', mode='w') as writer:
                for command in commands:
                    try:
                        # Komutu temizle ve büyük harfe çevir (kontrol için)
                        clean_command = command.strip().upper()
                        
                        # Komutu çalıştır
                        cursor.execute(command)
                        
                        # DDL komutları için otomatik commit
                        if any(clean_command.startswith(ddl) for ddl in ['CREATE', 'DROP', 'ALTER', 'TRUNCATE']):
                            connection.commit()
                            results.append(f"DDL komutu başarıyla çalıştırıldı: {command[:100]}...")
                        else:
                            # DML komutları için etkilenen satır sayısını kontrol et
                            if cursor.rowcount > 0:
                                results.append(f"{cursor.rowcount} satır etkilendi")
                                connection.commit()
                        
                        # SELECT sorguları için sonuçları topla
                        if clean_command.startswith('SELECT') or clean_command.startswith('WITH'):
                            if cursor.description:
                                # Sütun isimlerini al
                                columns = [col[0] for col in cursor.description]
                                
                                # Sayfa adını oluştur
                                sheet_name = f"Sorgu {query_count}"
                                clean_sheet_name = "".join(c for c in sheet_name if c.isalnum() or c in (' ', '-', '_'))[:31]
                                
                                # Chunk size'ı belirle (örn: 10000 satır)
                                chunk_size = 10000
                                first_chunk = True
                                row_count = 0
                                
                                while True:
                                    # Chunk'ı al
                                    rows = cursor.fetchmany(chunk_size)
                                    if not rows:
                                        break
                                        
                                    # NumPy array'e çevir (daha hızlı)
                                    data = np.array(rows)
                                    
                                    # DataFrame oluştur
                                    df_chunk = pd.DataFrame(data, columns=columns)
                                    
                                    # Excel'e yaz
                                    if first_chunk:
                                        df_chunk.to_excel(writer, sheet_name=clean_sheet_name, index=False)
                                        first_chunk = False
                                    else:
                                        # Mevcut sayfaya ekle
                                        df_chunk.to_excel(writer, sheet_name=clean_sheet_name, 
                                                        index=False, header=False, 
                                                        startrow=row_count + 1)  # +1 for header
                                    
                                    row_count += len(df_chunk)
                                    
                                    # Belleği temizle
                                    del df_chunk
                                    
                                query_count += 1
                                results.append(f"Sorgu başarıyla çalıştırıldı ve {row_count} satır veri alındı")
                    
                    except Exception as e:
                        # Hata durumunda rollback yap
                        connection.rollback()
                        results.append(f"Hata: {str(e)} - Komut: {command[:100]}...")

            # Bağlantıyı kapat
            cursor.close()
            connection.close()

            # Adımın durumunu güncelle
            from app import db
            step.status = 'completed'
            step.completed_at = datetime.now()
            db.session.commit()

            return {
                'status': 'success',
                'message': 'SQL script başarıyla çalıştırıldı',
                'output': '\n'.join(results),
                'has_excel_output': query_count > 1,  # En az bir sorgu çalıştırıldıysa
                'excel_filename': excel_filename if query_count > 1 else None
            }

        except Exception as e:
            # Hata durumunda adımın durumunu güncelle
            from app import db
            step.status = 'failed'
            step.error_message = str(e)
            db.session.commit()
            
            return {
                'status': 'error',
                'message': f'SQL script çalıştırılırken hata oluştu: {str(e)}'
            }

    @staticmethod
    def execute_step(step_type, file_path, **kwargs):
        """Adımı tipine göre çalıştırır"""
        check_result = ProcessExecutor.check_process_started()
        if check_result:
            return check_result
            
        
        elif step_type == 'mail':
            variables = kwargs.get('variables', [])
            if not variables:
                return {
                    'success': False,
                    'output': None,
                    'error': 'Mail değişkenleri bulunamadı'
                }
            mail_configs = []
            for var in variables:
                if var.var_type == 'mail_config':
                    try:
                        config = json.loads(var.default_value) if var.default_value else {}
                        mail_configs.append(config)
                    except:
                        continue
            if not mail_configs:
                return {
                    'success': False,
                    'output': None,
                    'error': 'Mail konfigürasyonu bulunamadı'
                }
            result = ProcessExecutor.send_mail(mail_configs)
            # Her başarılı gönderim için sent_at güncelle
            for idx, var in enumerate(variables):
                if var.var_type == 'mail_config':
                    try:
                        config = json.loads(var.default_value) if var.default_value else {}
                        if idx < len(result['results']) and result['results'][idx]['success']:
                            config['sent_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                            var.default_value = json.dumps(config)
                    except:
                        continue
            return result
        else:
            return {
                'success': True,
                'output': 'Bu adım tipi otomatik çalıştırılmaz',
                'error': None
            } 

    @staticmethod
    def execute_import_process(import_process):
        """Excel import process'ini çalıştırır"""
        try:
            # Excel dosyasını oku
            df = pd.read_excel(import_process.file_path, sheet_name=import_process.sheet_name)
            
            # Oracle bağlantısını oluştur
            import oracledb
            connection = oracledb.connect(
                user=ProcessExecutor._oracle_config['username'],
                password=ProcessExecutor._oracle_config['password'],
                dsn=ProcessExecutor._oracle_config['dsn']
            )
            cursor = connection.cursor()
            
            # Kolon eşleştirmelerini al
            column_mappings = json.loads(import_process.column_mappings)
            
            # Verileri Oracle'a aktar
            if import_process.import_mode == 'append':
                # Mevcut tabloya ekle
                oracle_columns = [mapping['oracle_column'] for mapping in column_mappings]
                excel_columns = [mapping['excel_column'] for mapping in column_mappings]
                placeholders = [f":{i+1}" for i in range(len(oracle_columns))]
                insert_sql = f"INSERT INTO {import_process.table_name} ({', '.join(oracle_columns)}) VALUES ({', '.join(placeholders)})"
                
                for _, row in df.iterrows():
                    values = [row[excel_col] for excel_col in excel_columns]
                    cursor.execute(insert_sql, values)
            
            elif import_process.import_mode == 'replace':
                # Tabloyu temizle ve yeniden oluştur
                cursor.execute(f"DROP TABLE {import_process.table_name}")
                
                # Yeni tablo oluştur
                create_table_sql = f"CREATE TABLE {import_process.table_name} ("
                for mapping in column_mappings:
                    create_table_sql += f"{mapping['oracle_column']} VARCHAR2(4000), "
                create_table_sql = create_table_sql.rstrip(", ") + ")"
                cursor.execute(create_table_sql)
                
                # Verileri ekle
                oracle_columns = [mapping['oracle_column'] for mapping in column_mappings]
                excel_columns = [mapping['excel_column'] for mapping in column_mappings]
                placeholders = [f":{i+1}" for i in range(len(oracle_columns))]
                insert_sql = f"INSERT INTO {import_process.table_name} ({', '.join(oracle_columns)}) VALUES ({', '.join(placeholders)})"
                
                for _, row in df.iterrows():
                    values = [row[excel_col] for excel_col in excel_columns]
                    cursor.execute(insert_sql, values)
            
            connection.commit()
            cursor.close()
            connection.close()
            
            # Son kullanım tarihini güncelle
            import_process.last_used_at = datetime.now()
            
            return {
                'status': 'success',
                'message': 'Excel verisi başarıyla içe aktarıldı.'
            }
            
        except Exception as e:
            return {
                'status': 'error',
                'message': f'Excel import sırasında hata oluştu: {str(e)}'
            } 