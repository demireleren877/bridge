// Değişken silme işlemi
async function deleteVariable(variableId) {
    if (!confirm('Bu değişkeni silmek istediğinizden emin misiniz?')) {
        return;
    }

    try {
        const response = await fetch(`/variable/${variableId}/delete`, {
            method: 'POST',
        });

        if (response.redirected) {
            window.location.href = response.url;
        }
    } catch (error) {
        console.error('Değişken silinirken hata oluştu:', error);
    }
}

// Alt adımları gizle/göster
document.addEventListener('DOMContentLoaded', () => {
    const mainSteps = document.querySelectorAll('.main-step');

    mainSteps.forEach(mainStep => {
        const stepId = mainStep.dataset.stepId;
        const subSteps = document.querySelectorAll(`.sub-step[data-parent-id="${stepId}"]`);

        if (subSteps.length > 0) {
            mainStep.style.cursor = 'pointer';

            mainStep.addEventListener('click', () => {
                subSteps.forEach(subStep => {
                    subStep.classList.toggle('d-none');
                });
            });
        }
    });

    // Değişkenleri gizle/göster
    document.querySelectorAll('.variables-header').forEach(header => {
        header.addEventListener('click', () => {
            const stepId = header.dataset.stepId;
            const container = document.querySelector(`.variables-container[data-step-id="${stepId}"]`);

            header.classList.toggle('expanded');
            container.classList.toggle('d-none');
        });
    });

    // Adım alanlarını düzenleme
    ['name', 'description', 'filepath', 'responsible'].forEach(field => {
        document.querySelectorAll(`.step-${field}`).forEach(element => {
            element.addEventListener('click', () => {
                const stepId = element.dataset.stepId;
                const input = document.querySelector(`.step-${field}-input[data-step-id="${stepId}"]`);

                element.classList.add('d-none');
                input.classList.remove('d-none');
                input.focus();

                // Önceki değeri sakla
                input.dataset.previousValue = input.value;
            });
        });

        document.querySelectorAll(`.step-${field}-input`).forEach(input => {
            const handleUpdate = async () => {
                const stepId = input.dataset.stepId;
                const element = document.querySelector(`.step-${field}[data-step-id="${stepId}"]`);
                const newValue = input.value.trim();

                if (newValue !== input.dataset.previousValue) {
                    try {
                        const response = await fetch(`/step/${stepId}/update`, {
                            method: 'POST',
                            headers: {
                                'Content-Type': 'application/x-www-form-urlencoded',
                            },
                            body: `field=${field}&value=${encodeURIComponent(newValue)}`
                        });

                        const result = await response.json();

                        if (result.success) {
                            element.textContent = newValue || `${field} ekle...`;
                            input.classList.add('is-valid');
                            setTimeout(() => input.classList.remove('is-valid'), 2000);
                        } else {
                            input.value = input.dataset.previousValue;
                            input.classList.add('is-invalid');
                            setTimeout(() => input.classList.remove('is-invalid'), 2000);
                        }
                    } catch (error) {
                        console.error(`${field} güncellenirken hata oluştu:`, error);
                        input.value = input.dataset.previousValue;
                        input.classList.add('is-invalid');
                        setTimeout(() => input.classList.remove('is-invalid'), 2000);
                    }
                } else {
                    input.value = input.dataset.previousValue;
                }

                input.classList.add('d-none');
                element.classList.remove('d-none');
            };

            // Enter tuşu ile güncelle (textarea hariç)
            if (field !== 'description') {
                input.addEventListener('keypress', (e) => {
                    if (e.key === 'Enter') {
                        e.preventDefault();
                        input.blur();
                    }
                });
            }

            // Input'tan çıkınca güncelle
            input.addEventListener('blur', handleUpdate);
        });
    });

    // Değişken değerlerini güncelle
    document.querySelectorAll('.variable-value').forEach(input => {
        input.addEventListener('change', async () => {
            const variableId = input.dataset.variableId;
            const value = input.type === 'checkbox' ? input.checked : input.value;
            const originalVariablesData = document.getElementById(`variables-data-${input.closest('.variables-container').dataset.stepId}`);

            try {
                const response = await fetch(`/variable/${variableId}/update`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/x-www-form-urlencoded',
                    },
                    body: `field=default_value&value=${encodeURIComponent(value)}`
                });

                const result = await response.json();

                if (!result.success) {
                    console.error('Değişken güncellenirken hata oluştu');
                    input.classList.add('is-invalid');
                    setTimeout(() => input.classList.remove('is-invalid'), 2000);
                } else {
                    // Başarılı güncelleme görsel geri bildirimi
                    input.classList.add('is-valid');
                    setTimeout(() => input.classList.remove('is-valid'), 2000);

                    // Ana sayfadaki değişken değerini güncelle
                    if (originalVariablesData) {
                        const originalInput = originalVariablesData.querySelector(`[data-variable-id="${variableId}"]`);
                        if (originalInput) {
                            if (input.type === 'checkbox') {
                                originalInput.checked = value;
                            } else {
                                originalInput.value = value;
                            }
                        }
                    }
                }
            } catch (error) {
                console.error('Değişken güncellenirken hata oluştu:', error);
                input.classList.add('is-invalid');
                setTimeout(() => input.classList.remove('is-invalid'), 2000);
            }
        });
    });

    // Değişken düzenleme işlevselliği
    document.querySelectorAll('.variable-name, .variable-description').forEach(element => {
        element.addEventListener('click', () => {
            const variableId = element.dataset.variableId;
            const field = element.classList.contains('variable-name') ? 'name' : 'description';
            const input = document.querySelector(`.variable-${field}-input[data-variable-id="${variableId}"]`);

            element.classList.add('d-none');
            input.classList.remove('d-none');
            input.focus();
            input.dataset.previousValue = input.value;
        });
    });

    document.querySelectorAll('.variable-name-input, .variable-description-input').forEach(input => {
        const handleUpdate = async () => {
            const variableId = input.dataset.variableId;
            const field = input.classList.contains('variable-name-input') ? 'name' : 'description';
            const element = document.querySelector(`.variable-${field}[data-variable-id="${variableId}"]`);
            const newValue = input.value.trim();
            const stepId = input.closest('.variables-container').dataset.stepId;
            const originalVariablesData = document.getElementById(`variables-data-${stepId}`);

            if (newValue !== input.dataset.previousValue) {
                try {
                    const response = await fetch(`/variable/${variableId}/update`, {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/x-www-form-urlencoded',
                        },
                        body: `field=${field}&value=${encodeURIComponent(newValue)}`
                    });

                    const result = await response.json();

                    if (result.success) {
                        element.textContent = newValue || `${field} ekle...`;
                        input.classList.add('is-valid');
                        setTimeout(() => input.classList.remove('is-valid'), 2000);

                        // Ana sayfadaki değişken adını/açıklamasını güncelle
                        if (originalVariablesData) {
                            const originalElement = originalVariablesData.querySelector(`.variable-${field}[data-variable-id="${variableId}"]`);
                            if (originalElement) {
                                originalElement.textContent = newValue || `${field} ekle...`;
                            }
                        }
                    } else {
                        input.value = input.dataset.previousValue;
                        input.classList.add('is-invalid');
                        setTimeout(() => input.classList.remove('is-invalid'), 2000);
                    }
                } catch (error) {
                    console.error(`Değişken ${field} güncellenirken hata oluştu:`, error);
                    input.value = input.dataset.previousValue;
                    input.classList.add('is-invalid');
                    setTimeout(() => input.classList.remove('is-invalid'), 2000);
                }
            }

            input.classList.add('d-none');
            element.classList.remove('d-none');
        };

        input.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                input.blur();
            }
        });

        input.addEventListener('blur', handleUpdate);
    });

    // Değişken tipini güncelle
    document.querySelectorAll('.variable-type').forEach(select => {
        select.addEventListener('change', async () => {
            const variableId = select.dataset.variableId;
            const newValue = select.value;
            const stepId = select.closest('.variables-container').dataset.stepId;
            const originalVariablesData = document.getElementById(`variables-data-${stepId}`);

            try {
                const response = await fetch(`/variable/${variableId}/update`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/x-www-form-urlencoded',
                    },
                    body: `field=var_type&value=${encodeURIComponent(newValue)}`
                });

                const result = await response.json();

                if (result.success) {
                    select.classList.add('is-valid');
                    setTimeout(() => select.classList.remove('is-valid'), 2000);

                    // Ana sayfadaki değişken tipini güncelle
                    if (originalVariablesData) {
                        const originalSelect = originalVariablesData.querySelector(`.variable-type[data-variable-id="${variableId}"]`);
                        if (originalSelect) {
                            originalSelect.value = newValue;
                        }
                    }
                } else {
                    select.classList.add('is-invalid');
                    setTimeout(() => select.classList.remove('is-invalid'), 2000);
                }
            } catch (error) {
                console.error('Değişken tipi güncellenirken hata oluştu:', error);
                select.classList.add('is-invalid');
                setTimeout(() => select.classList.remove('is-invalid'), 2000);
            }
        });
    });

    // Değişken gösterme butonu için event listener
    document.querySelectorAll('.show-variables').forEach(button => {
        button.addEventListener('click', () => {
            const stepId = button.dataset.stepId;
            const variablesData = document.getElementById(`variables-data-${stepId}`);
            const variablesContainer = document.getElementById('variables-container');
            if (variablesData) {
                variablesContainer.innerHTML = variablesData.innerHTML;
                variablesContainer.dataset.stepId = stepId;
                const modal = new bootstrap.Modal(document.getElementById('variablesModal'));
                modal.show();
            }
        });
    });
});

// Form doğrulama
document.querySelectorAll('form').forEach(form => {
    form.addEventListener('submit', event => {
        if (!form.checkValidity()) {
            event.preventDefault();
            event.stopPropagation();
        }
        form.classList.add('was-validated');
    });
});

// Tooltip'leri etkinleştir
const tooltipTriggerList = document.querySelectorAll('[data-bs-toggle="tooltip"]');
const tooltipList = [...tooltipTriggerList].map(tooltipTriggerEl => new bootstrap.Tooltip(tooltipTriggerEl));

// Modal'ı otomatik temizle
const resultModal = document.getElementById('resultModal');
if (resultModal) {
    resultModal.addEventListener('hidden.bs.modal', () => {
        document.getElementById('resultSuccess').classList.add('d-none');
        document.getElementById('resultError').classList.add('d-none');
    });
} 