import shutil
import subprocess
import os
import pandas as pd
import sqlite3
import json
from datetime import datetime
import platform
import logging

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
    def execute_step(step_type, file_path, **kwargs):
        """Adımı tipine göre çalıştırır"""
        check_result = ProcessExecutor.check_process_started()
        if check_result:
            return check_result
            
        if step_type == 'python_script':
            # Python script çalıştırılmadan önce çıktı dizinindeki dosyaları kaydet
            output_dir = os.path.join(os.environ['USERPROFILE'], 'Downloads')
            print(f"[DEBUG] output_dir: {output_dir}")
            if output_dir:
                ProcessExecutor._files_before = set(os.listdir(output_dir))
            return ProcessExecutor.execute_python_script(file_path, output_dir,kwargs.get('variables'))
        elif step_type == 'sql_script':
            return ProcessExecutor.execute_sql_script(file_path)
        elif step_type == 'sql_procedure':
            return ProcessExecutor.execute_sql_script(file_path, is_procedure=True)
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