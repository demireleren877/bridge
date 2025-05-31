// Mail durumu yönetimi için merkezi fonksiyonlar
class MailStatusManager {
    static async checkMailReplies(stepId) {
        console.log('Starting checkMailReplies for stepId:', stepId); // Debug log

        // Ana sayfadaki ve değişkenler modalındaki tüm mail durumlarını seç
        const mailStatuses = document.querySelectorAll(`tr[data-step-id="${stepId}"] .mail-status, #variables-data-${stepId} .mail-status, #variablesModal .mail-status`);
        console.log('Found mail status elements:', mailStatuses.length); // Debug log
        
        if (!mailStatuses.length) {
            console.log('No mail status elements found, returning'); // Debug log
            return;
        }

        try {
            console.log('Sending request to check mail replies...'); // Debug log
            const response = await fetch(`/step/${stepId}/check-mail-replies`, {
                method: 'POST'
            });
            console.log('Response received:', response.status); // Debug log
            
            const result = await response.json();
            console.log('Mail check response:', result); // Debug log

            if (result.success && result.mail_statuses) {
                console.log('Processing mail statuses:', result.mail_statuses); // Debug log
                let allActiveMailsReplied = true;
                let hasActiveMail = false;

                result.mail_statuses.forEach(statusData => {
                    console.log('Processing mail status data:', statusData); // Debug log
                    
                    // Hem ana sayfadaki hem de modaldaki durumları güncelle
                    const statusElements = document.querySelectorAll(`.mail-status[data-variable-id="${statusData.variable_id}"]`);
                    console.log('Found status elements for variable:', statusData.variable_id, 'count:', statusElements.length); // Debug log
                    
                    // Config'i parse et
                    let config = {};
                    statusElements.forEach(status => {
                        try {
                            const configStr = status.dataset.config;
                            console.log('Raw config string:', configStr); // Debug log
                            config = JSON.parse(configStr);
                            console.log('Parsed config:', config); // Debug log
                        } catch (e) {
                            console.error('Config parsing error:', e);
                            console.error('Config string was:', status.dataset.config); // Debug log
                        }
                    });
                    
                    if (config.active) {
                        console.log('Mail is active'); // Debug log
                        hasActiveMail = true;
                        const hasReplies = statusData.status === 'received' && statusData.replies && statusData.replies.length > 0;
                        console.log('Has replies:', hasReplies, 'Status:', statusData.status, 'Replies:', statusData.replies); // Debug log
                        
                        if (!hasReplies) {
                            console.log('Setting allActiveMailsReplied to false'); // Debug log
                            allActiveMailsReplied = false;
                        }
                    }
                    
                    statusElements.forEach(status => {
                        const hasReplies = statusData.status === 'received' && statusData.replies && statusData.replies.length > 0;
                        console.log('Updating status element. Has replies:', hasReplies);
                        
                        if (statusData.status === 'not_sent') {
                            status.className = 'mail-status me-2 no-reply text-warning';
                            status.innerHTML = `
                                <div>
                                    <i class="bi bi-envelope"></i>
                                    <span class="status-text">Gönderilmedi</span>
                                </div>
                            `;
                        } else if (hasReplies) {
                            const lastReply = statusData.replies[statusData.replies.length - 1];
                            console.log('Last reply:', lastReply); // Debug log
                            
                            status.className = 'mail-status me-2 has-reply text-success';
                            status.innerHTML = `
                                <div>
                                    <i class="bi bi-check-circle-fill"></i>
                                    <span class="status-text">Yanıt Alındı</span>
                                    <div class="reply-details mt-2">
                                        <small class="d-block text-muted">Son yanıt:</small>
                                        <div class="reply-info">
                                            <strong>${lastReply.sender}</strong>
                                            <span class="mx-1">-</span>
                                            <span>${new Date(lastReply.received_at).toLocaleString('tr-TR')}</span>
                                        </div>
                                    </div>
                                </div>
                            `;
                        } else if (config.active) {
                            console.log('Mail is active but no replies'); // Debug log
                            status.className = 'mail-status me-2 no-reply text-warning';
                            status.innerHTML = `
                                <div>
                                    <i class="bi bi-hourglass"></i>
                                    <span class="status-text">Yanıt Bekleniyor</span>
                                    ${config.sent_at ? `
                                    <div class="reply-details mt-2">
                                        <small class="d-block text-muted">Gönderilme:</small>
                                        <div class="reply-info">
                                            <span>${new Date(config.sent_at).toLocaleString('tr-TR')}</span>
                                        </div>
                                    </div>
                                    ` : ''}
                                </div>
                            `;
                        } else {
                            console.log('Mail is inactive'); // Debug log
                            status.className = 'mail-status me-2';
                            status.innerHTML = `
                                <div>
                                    <i class="bi bi-dash-circle"></i>
                                    <span class="status-text">Pasif</span>
                                </div>
                            `;
                        }
                    });
                });

                // Eğer aktif mail varsa ve tüm aktif maillere yanıt geldiyse adımı tamamlandı olarak işaretle
                if (hasActiveMail && allActiveMailsReplied) {
                    console.log('All mails replied, updating step status to done'); // Debug log
                    this.updateStepStatus(stepId, 'done', 'Tamamlandı');
                } else {
                    console.log('Not all mails replied:', { hasActiveMail, allActiveMailsReplied }); // Debug log
                }
            } else {
                console.log('Response was not successful or no mail statuses:', result); // Debug log
            }
        } catch (error) {
            console.error('Mail durumu kontrol edilirken hata oluştu:', error);
            console.error('Error details:', error.stack); // Debug log
        }
    }

    static updateStepStatus(stepId, status, statusText) {
        const stepElement = document.querySelector(`tr[data-step-id="${stepId}"]`);
        if (stepElement) {
            const statusButton = stepElement.querySelector('.status-button');
            if (statusButton) {
                // Durum butonunun sınıflarını güncelle
                statusButton.className = `btn btn-sm dropdown-toggle status-button ${
                    status === 'done' ? 'btn-success' :
                    status === 'in_progress' ? 'btn-primary' :
                    status === 'waiting' ? 'btn-warning' :
                    'btn-secondary'
                }`;
                
                // Durum metnini güncelle
                const statusTextElement = statusButton.querySelector('.status-text');
                if (statusTextElement) {
                    statusTextElement.textContent = statusText;
                } else {
                    statusButton.textContent = statusText;
                }
            }
        }
    }

    static updateMailStatuses(stepId, mailStatuses) {
        // Her bir mail durumunu güncelle
        Object.entries(mailStatuses).forEach(([variableId, status]) => {
            const statusElements = document.querySelectorAll(`.mail-status[data-variable-id="${variableId}"]`);
            statusElements.forEach(statusElement => {
                if (statusElement) {
                    // Mail durumunu güncelle
                    statusElement.className = `mail-status me-2 ${status === 'received' ? 'has-reply text-success' : 'no-reply text-warning'}`;
                    
                    // Mail konfigürasyonunu al
                    const config = JSON.parse(statusElement.dataset.config || '{}');
                    
                    // Durum metnini güncelle
                    let statusHtml = '';
                    if (status === 'received') {
                        statusHtml = `
                            <i class="bi bi-check-circle-fill"></i>
                            <span class="status-text">Yanıt Alındı</span>
                        `;
                    } else if (config.sent_at) {
                        statusHtml = `
                            <i class="bi bi-hourglass"></i>
                            <span class="status-text">Yanıt Bekleniyor</span>
                            <div class="reply-details mt-2">
                                <small class="d-block text-muted">Gönderilme:</small>
                                <div class="reply-info">
                                    <span>${config.sent_at}</span>
                                </div>
                            </div>
                        `;
                    } else {
                        statusHtml = `
                            <i class="bi bi-envelope"></i>
                            <span class="status-text">Gönderilmedi</span>
                        `;
                    }
                    
                    statusElement.innerHTML = statusHtml;
                }
            });
        });
    }

    static markStepAsDone(stepId) {
        const stepElement = document.querySelector(`#step${stepId}`);
        if (stepElement) {
            stepElement.classList.add('completed');
            const statusBadge = stepElement.querySelector('.step-status');
            if (statusBadge) {
                statusBadge.textContent = 'Tamamlandı';
                statusBadge.className = 'badge bg-success step-status';
            }
        }
    }

    static initializeMailStatusCheck() {
        document.querySelectorAll('.check-mail-status').forEach(button => {
            button.addEventListener('click', async () => {
                const stepId = button.dataset.stepId;
                button.disabled = true;
                try {
                    await MailStatusManager.checkMailReplies(stepId);
                } finally {
                    button.disabled = false;
                }
            });
        });
    }
}

// Mail gönderme işlemi
async function sendMail(stepId) {
    const form = document.getElementById(`mailForm${stepId}`);
    const formData = new FormData(form);
    
    try {
        const response = await fetch(`/step/${stepId}/send_mail`, {
            method: 'POST',
            body: formData
        });
        
        if (response.ok) {
            const result = await response.json();
            if (result.success) {
                // Mail başarıyla gönderildi, durumu güncelle
                await MailStatusManager.checkMailReplies(stepId);
                
                // Modal'ı kapat
                const modal = bootstrap.Modal.getInstance(document.getElementById(`mailModal${stepId}`));
                modal.hide();
                
                // Başarı mesajını göster
                showAlert('success', 'Mail başarıyla gönderildi.');
                
                // Mail durumlarını güncelle
                const mailStatuses = {};
                result.mail_statuses.forEach(status => {
                    mailStatuses[status.variable_id] = status.status;
                    // Mail konfigürasyonunu güncelle
                    const statusElement = document.querySelector(`.mail-status[data-variable-id="${status.variable_id}"]`);
                    if (statusElement && status.config) {
                        statusElement.dataset.config = JSON.stringify(status.config);
                    }
                });
                MailStatusManager.updateMailStatuses(stepId, mailStatuses);
            } else {
                showAlert('error', result.error || 'Mail gönderilirken bir hata oluştu.');
            }
        } else {
            showAlert('error', 'Mail gönderilirken bir hata oluştu.');
        }
    } catch (error) {
        console.error('Mail gönderme hatası:', error);
        showAlert('error', 'Mail gönderme hatası:', error);
    }
}

// Sayfa yüklendiğinde mail durumu kontrollerini başlat
document.addEventListener('DOMContentLoaded', () => {
    MailStatusManager.initializeMailStatusCheck();
}); 