from flask import Flask, request, jsonify, render_template, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_cors import CORS
from datetime import datetime
import os
from executor import ProcessExecutor
import json
from collections import Counter
import re
import pandas as pd
import oracledb
from werkzeug.utils import secure_filename
from sqlalchemy import inspect

app = Flask(__name__)
CORS(app)

app.secret_key = 'your-super-secret-key-here'  

# Oracle veritabanı bağlantı ayarları
app.config['ORACLE_USERNAME'] = 'your_username'
app.config['ORACLE_PASSWORD'] = 'your_password'
app.config['ORACLE_DSN'] = 'your_dsn'

# Oracle bağlantı bilgilerini executor'a ilet
ProcessExecutor.set_oracle_config(
    username="your_username",
    password="your_password",
    dsn="your_dsn"
)

# SQLite veritabanı ayarları
os.makedirs(app.instance_path, exist_ok=True)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(app.instance_path, 'processes.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

@app.template_filter('from_json')
def from_json(value):
    try:
        return json.loads(value)
    except:
        return {}

@app.template_filter('format_datetime')
def format_datetime(value):
    if not value:
        return ''
    try:
        if isinstance(value, str):
            dt = datetime.strptime(value, '%Y-%m-%d %H:%M:%S')
        else:
            dt = value
        return dt.strftime('%d.%m.%Y %H:%M')
    except:
        return value

@app.template_global()
def get_mail_replies(variable_id):
    return MailReply.query.filter_by(
        variable_id=variable_id,
        is_reply=True
    ).order_by(MailReply.received_at.asc()).all()

db = SQLAlchemy(app)
migrate = Migrate(app, db)
ProcessExecutor.set_db_path(os.path.join(app.instance_path, 'processes.db'))


class ProcessCategory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.now)
    processes = db.relationship('Process', backref='category', lazy=True)

class Process(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.now)
    is_started = db.Column(db.Boolean, default=False)
    started_at = db.Column(db.DateTime)
    version = db.Column(db.Integer, nullable=False, default=1)
    year = db.Column(db.Integer, nullable=False, default=lambda: datetime.now().year)
    category_id = db.Column(db.Integer, db.ForeignKey('process_category.id', name='fk_process_category'), nullable=True)
    steps = db.relationship('Step', backref='process', lazy=True, cascade='all, delete-orphan')

    def get_completion_percentage(self):
        all_steps = []
        main_steps = Step.query.filter_by(process_id=self.id, parent_id=None).all()
        
        for main_step in main_steps:
            all_steps.append(main_step)
            substeps = Step.query.filter_by(process_id=self.id).filter(Step.parent_id == main_step.id).all()
            all_steps.extend(substeps)
            for substep in substeps:
                sub_substeps = Step.query.filter_by(process_id=self.id).filter(Step.parent_id == substep.id).all()
                all_steps.extend(sub_substeps)
        
        total_steps = len(all_steps)
        if total_steps == 0:
            return 0
        
        completed_steps = sum(1 for step in all_steps if step.status == 'done')
        return int((completed_steps / total_steps) * 100)

    def get_status(self):
        if not self.is_started:
            return 'not_started'
        all_steps = []
        main_steps = Step.query.filter_by(process_id=self.id, parent_id=None).all()
        
        for main_step in main_steps:
            all_steps.append(main_step)
            substeps = Step.query.filter_by(process_id=self.id).filter(Step.parent_id == main_step.id).all()
            all_steps.extend(substeps)
            for substep in substeps:
                sub_substeps = Step.query.filter_by(process_id=self.id).filter(Step.parent_id == substep.id).all()
                all_steps.extend(sub_substeps)
        
        if not all_steps:
            return 'empty'
        
        all_done = all(step.status == 'done' for step in all_steps)
        has_in_progress = any(step.status == 'in_progress' for step in all_steps)
        has_waiting = any(step.status == 'waiting' for step in all_steps)
        
        if all_done:
            return 'done'
        elif has_in_progress:
            return 'in_progress'
        elif has_waiting:
            return 'waiting'
        else:
            return 'not_started'

class Step(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    step_number = db.Column(db.Integer)  
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    type = db.Column(db.String(50))  
    file_path = db.Column(db.String(255))
    order = db.Column(db.Integer)
    parent_id = db.Column(db.Integer, db.ForeignKey('step.id', ondelete='CASCADE'), nullable=True)
    process_id = db.Column(db.Integer, db.ForeignKey('process.id', ondelete='CASCADE'), nullable=False)
    responsible = db.Column(db.String(100))
    status = db.Column(db.String(20), default='not_started')
    version = db.Column(db.Integer, nullable=False, default=1)
    deadline = db.Column(db.DateTime, nullable=True)
    dependencies = db.relationship('StepDependency', 
                                 foreign_keys='StepDependency.step_id',
                                 backref='dependent_step', 
                                 lazy=True,
                                 cascade='all, delete-orphan')
    sub_steps = db.relationship('Step',
                              backref=db.backref('parent', remote_side=[id]),
                              lazy=True,
                              cascade='all, delete-orphan')
    variables = db.relationship('StepVariable', 
                              backref='step', 
                              lazy=True,
                              cascade='all, delete-orphan')
    completed_at = db.Column(db.DateTime)

    def __init__(self, **kwargs):
        super(Step, self).__init__(**kwargs)
        if self.order is None:
            last_step = Step.query.filter_by(
                process_id=self.process_id,
                parent_id=self.parent_id
            ).order_by(Step.order.desc()).first()
            self.order = (last_step.order + 1) if last_step else 1

        if self.status is None:
            self.status = 'not_started'
            
        if self.step_number is None:
            last_step = Step.query.filter_by(
                process_id=self.process_id
            ).order_by(Step.step_number.desc()).first()
            self.step_number = (last_step.step_number + 1) if last_step else 1

    def get_full_order(self):
        if not self.parent_id:
            return str(self.order)
        
        parent = self.parent
        if not parent.parent_id:
            return f"{parent.order}.{self.order}"
        else:
            return f"{parent.get_full_order()}.{self.order}"

    def get_step_id(self):
        return f"{self.process_id}_{self.step_number}"

    def update_status(self):
        if not self.sub_steps: 
            return self.status
        
        all_not_started = all(step.status == 'not_started' for step in self.sub_steps)
        has_in_progress = any(step.status == 'in_progress' for step in self.sub_steps)
        has_waiting = any(step.status == 'waiting' for step in self.sub_steps)
        all_done = all(step.status == 'done' for step in self.sub_steps)
        
        old_status = self.status
        
        if has_in_progress:
            self.status = 'in_progress'
            if self.completed_at is not None:
                self.completed_at = None
        elif has_waiting:
            self.status = 'waiting'
            if self.completed_at is not None:
                self.completed_at = None
        elif all_not_started:
            self.status = 'not_started'
            if self.completed_at is not None:
                self.completed_at = None
        elif all_done:
            self.status = 'done'
            # Eğer tüm alt adımlar tamamlandıysa ve ana adımın tamamlanma tarihi yoksa
            if self.completed_at is None:
                # En son tamamlanan alt adımın tarihini al
                latest_completion = max(step.completed_at for step in self.sub_steps if step.completed_at is not None)
                self.completed_at = latest_completion
        else:
            self.status = 'in_progress'         
            if self.completed_at is not None:
                self.completed_at = None
                
        return self.status

class StepDependency(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    step_id = db.Column(db.Integer, db.ForeignKey('step.id'), nullable=False)
    depends_on_id = db.Column(db.Integer, db.ForeignKey('step.id'), nullable=False)

class StepVariable(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    step_id = db.Column(db.Integer, db.ForeignKey('step.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    var_type = db.Column(db.String(50), nullable=False)  
    default_value = db.Column(db.String(255))
    scope = db.Column(db.String(20), nullable=False, default='step_only', server_default='step_only')  
    parent_variable_id = db.Column(db.Integer, db.ForeignKey('step_variable.id', name='fk_parent_variable', ondelete='CASCADE'), nullable=True)
    mail_status = db.Column(db.String(20), default='waiting') 
    
    child_variables = db.relationship('StepVariable',
                                    backref=db.backref('parent_variable', remote_side=[id]),
                                    cascade="all, delete-orphan",
                                    passive_deletes=True)

class MailReply(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    variable_id = db.Column(db.Integer, db.ForeignKey('step_variable.id', ondelete='CASCADE'), nullable=False)
    subject = db.Column(db.String(255))
    sender = db.Column(db.String(255))
    received_at = db.Column(db.DateTime, default=datetime.now)
    original_subject = db.Column(db.String(255))
    is_reply = db.Column(db.Boolean, default=False)

@app.route('/')
def index():
    categories = ProcessCategory.query.all()
    uncategorized_count = Process.query.filter_by(category_id=None).count()
    return render_template('categories.html', 
                         categories=categories,
                         uncategorized_count=uncategorized_count)

@app.route('/category/<int:category_id>')
def category_years(category_id):
    category = ProcessCategory.query.get_or_404(category_id)
    processes = Process.query.filter_by(category_id=category_id).all()
    years = sorted(set(process.year for process in processes))
    processes_by_year = {}
    for year in years:
        processes_by_year[year] = len([p for p in processes if p.year == year])
    return render_template('category_years.html', 
                         category=category,
                         years=years,
                         processes_by_year=processes_by_year)

@app.route('/category/<int:category_id>/<int:year>')
def category_processes(category_id, year):
    category = ProcessCategory.query.get_or_404(category_id)
    processes = Process.query.filter_by(category_id=category_id, year=year).all()
    all_categories = ProcessCategory.query.all()
    current_year = datetime.now().year
    return render_template('process_list.html', 
                         category=category,
                         year=year,
                         processes=processes,
                         is_uncategorized=False,
                         all_categories=all_categories,
                         current_year=current_year)

@app.route('/uncategorized')
def uncategorized_years():
    processes = Process.query.filter_by(category_id=None).all()
    years = sorted(set(process.year for process in processes))
    processes_by_year = {}
    for year in years:
        processes_by_year[year] = len([p for p in processes if p.year == year])
    return render_template('uncategorized_years.html', 
                         years=years,
                         processes_by_year=processes_by_year)

@app.route('/uncategorized/<int:year>')
def uncategorized_processes(year):
    processes = Process.query.filter_by(category_id=None, year=year).all()
    all_categories = ProcessCategory.query.all()
    current_year = datetime.now().year
    return render_template('process_list.html', 
                         year=year,
                         processes=processes,
                         is_uncategorized=True,
                         all_categories=all_categories,
                         current_year=current_year)

@app.route('/process/<int:process_id>')
def process_detail(process_id):
    process = Process.query.get_or_404(process_id)
    main_steps = Step.query.filter_by(
        process_id=process_id,
        parent_id=None
    ).order_by(Step.order).all()
    organized_steps = []
    for main_step in main_steps:
        organized_steps.append(main_step)
        organized_steps.extend(get_substeps_recursive(main_step.id))    
    return render_template('process_detail.html', 
                         process=process, 
                         steps=organized_steps,
                         now=datetime.now())

def get_substeps_recursive(parent_id):
    substeps = []
    direct_substeps = Step.query.filter_by(parent_id=parent_id).order_by(Step.order).all()    
    for substep in direct_substeps:
        substeps.append(substep)
        substeps.extend(get_substeps_recursive(substep.id))    
    return substeps

@app.route('/process/new', methods=['GET', 'POST'])
def new_process():
    if request.method == 'POST':
        name = request.form.get('name')
        description = request.form.get('description')
        category_id = request.form.get('category_id')
        year = request.form.get('year', type=int)
        
        if name and year:
            try:
                process = Process(
                    name=name,
                    description=description,
                    category_id=category_id if category_id else None,
                    year=year
                )
                db.session.add(process)
                db.session.commit()
                
                if category_id:
                    return redirect(url_for('category_processes', category_id=category_id, year=year))
                else:
                    return redirect(url_for('uncategorized_processes', year=year))
            except Exception as e:
                db.session.rollback()
                flash(f'Süreç oluşturulurken hata oluştu: {str(e)}', 'error')
    
    categories = ProcessCategory.query.all()
    current_year = datetime.now().year
    return render_template('new_process.html', 
                         categories=categories,
                         current_year=current_year)

@app.route('/process/<int:process_id>/delete', methods=['POST'])
def delete_process(process_id):
    try:
        process = Process.query.get_or_404(process_id)
        all_steps = []
        main_steps = Step.query.filter_by(process_id=process_id, parent_id=None).all()        
        for main_step in main_steps:
            all_steps.append(main_step)
            substeps = Step.query.filter_by(process_id=process_id).filter(Step.parent_id == main_step.id).all()
            all_steps.extend(substeps)
            for substep in substeps:
                sub_substeps = Step.query.filter_by(process_id=process_id).filter(Step.parent_id == substep.id).all()
                all_steps.extend(sub_substeps)
        
        for step in all_steps:
            StepVariable.query.filter_by(step_id=step.id).delete()            
            StepDependency.query.filter_by(step_id=step.id).delete()
            StepDependency.query.filter_by(depends_on_id=step.id).delete()

        db.session.delete(process)
        
        db.session.commit()
        
        flash('Süreç ve tüm ilişkili veriler başarıyla silindi', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Süreç silinirken hata oluştu: {str(e)}', 'error')
    
    return redirect(url_for('index'))

@app.route('/process/<int:process_id>/step/new', methods=['GET', 'POST'])
def new_step(process_id):
    process = Process.query.get_or_404(process_id)    
    if process.is_started:
        flash('Başlatılmış süreçlere yeni adım eklenemez.', 'error')
        return redirect(url_for('process_detail', process_id=process_id))    
    parent_id = request.args.get('parent_id', type=int)    
    if request.method == 'POST':
        name = request.form.get('name')
        description = request.form.get('description')
        step_type = request.form.get('type')
        file_path = request.form.get('file_path')
        responsible = request.form.get('responsible')        
        if name and step_type:
            try:
                # Ana adım tipi seçildiyse file_path ve procedure_params alanlarını temizle
                if step_type == 'main_step':
                    file_path = None
                
                step = Step(
                    name=name,
                    description=description,
                    type=step_type,
                    file_path=file_path,
                    responsible=responsible,
                    parent_id=parent_id,
                    process_id=process_id
                )
                db.session.add(step)
                db.session.commit()                
                app.logger.info(f'New step created - ID: {step.id}, Type: {step_type}')
                variables = StepVariable.query.filter_by(step_id=step.id).all()
                app.logger.info(f'Variables for step {step.id}: {[{"id": v.id, "name": v.name} for v in variables]}')                
                flash('Adım başarıyla oluşturuldu', 'success')
                return redirect(url_for('process_detail', process_id=process_id))
            except Exception as e:
                db.session.rollback()
                flash(f'Adım oluşturulurken hata oluştu: {str(e)}', 'error')
            return redirect(url_for('process_detail', process_id=process_id))    
    parent_step = None
    full_order = None
    if parent_id:
        parent_step = Step.query.get(parent_id)
        if parent_step:
            next_order = 1
            last_substep = Step.query.filter_by(parent_id=parent_id).order_by(Step.order.desc()).first()
            if last_substep:
                next_order = last_substep.order + 1
            full_order = f"{parent_step.get_full_order()}.{next_order}"    
    return render_template('new_step.html', 
                         process=process, 
                         parent_id=parent_id, 
                         parent_step=parent_step,
                         full_order=full_order)

@app.route('/step/<int:step_id>/execute', methods=['POST'])
def execute_step(step_id):
    step = Step.query.get_or_404(step_id)
    
    if step.status == 'done':
        return jsonify({
            'success': False,
            'message': 'Bu adım zaten tamamlandı.'
        })        
    
    # Adımı çalıştır
    result = ProcessExecutor.execute_step(
        step.type,
        step.file_path,
        output_dir=step.output_dir if hasattr(step, 'output_dir') else None,
        variables=step.variables if hasattr(step, 'variables') else None
    )
    
    if result['success']:
        step.status = 'done'
        step.completed_at = datetime.now()  # Tamamlanma zamanını kaydet
        db.session.commit()
    
    return jsonify(result)


@app.route('/step/<int:step_id>/variables/new', methods=['GET', 'POST'])
def new_variable(step_id):
    step = Step.query.get_or_404(step_id)    
    if step.type == 'main_step' or step.type not in ['python_script', 'sql_script', 'sql_procedure', 'mail']:
        flash('Bu adım tipine değişken eklenemez.', 'error')
        return redirect(url_for('process_detail', process_id=step.process_id))    
    if request.method == 'POST':
        name = request.form.get('name')
        var_type = request.form.get('var_type')
        default_value = request.form.get('default_value')
        scope = request.form.get('scope', 'step_only')        
        if step.type == 'mail' and var_type != 'mail_config':
            flash('Mail tipi adımlarda sadece mail konfigürasyonu eklenebilir.', 'error')
            return redirect(url_for('new_variable', step_id=step_id))        
        if name and var_type:            
            parent_variable_id = None
            if step.parent_id and scope == 'process_wide':
                parent_variable_id = request.form.get('parent_variable_id')
                if not parent_variable_id:
                    flash('Süreç genelinde değişken için ana adımdan bir değişken seçmelisiniz.', 'error')
                    return redirect(url_for('new_variable', step_id=step_id))
            
            variable = StepVariable(
                step_id=step_id,
                name=name,
                var_type=var_type,
                default_value=default_value,
                scope=scope,
                parent_variable_id=parent_variable_id,
                mail_status='waiting' if var_type == 'mail_config' else None
            )
            db.session.add(variable)
            db.session.commit()            
            if var_type == 'mail_config':                
                MailReply.query.filter_by(variable_id=variable.id).delete()
                db.session.commit()
            return redirect(url_for('process_detail', process_id=step.process_id))    
    parent_variables = []
    if step.parent_id:
        parent_variables = StepVariable.query.filter_by(step_id=step.parent_id).all()    
    is_mail_step = step.type == 'mail'
    return render_template('new_variable.html', 
                         step=step, 
                         parent_variables=parent_variables,
                         is_mail_step=is_mail_step)


@app.route('/variable/<int:variable_id>/update', methods=['POST'])
def update_variable(variable_id):
    variable = StepVariable.query.get_or_404(variable_id)
    field = request.form.get('field')
    value = request.form.get('value')    
    if field and value is not None:
        if field == 'name':
            variable.name = value
        elif field == 'var_type':
            variable.var_type = value
        elif field == 'default_value':
            variable.default_value = value        
        db.session.commit()
        return jsonify({'success': True})    
    return jsonify({'success': False}), 400


@app.route('/variable/<int:variable_id>/delete', methods=['POST'])
def delete_variable(variable_id):
    try:
        variable = StepVariable.query.get_or_404(variable_id)
        step_id = variable.step_id
        process_id = Step.query.get(step_id).process_id        
        StepVariable.query.filter_by(parent_variable_id=variable_id).delete()
        db.session.delete(variable)
        db.session.commit()        
        flash('Değişken başarıyla silindi', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Değişken silinirken hata oluştu: {str(e)}', 'error')    
    return redirect(url_for('process_detail', process_id=process_id))


@app.route('/step/<int:step_id>/update', methods=['POST'])
def update_step_field(step_id):
    step = Step.query.get_or_404(step_id)
    field = request.form.get('field')
    value = request.form.get('value')
    
    allowed_fields = ['name', 'description', 'responsible', 'file_path']
    if field not in allowed_fields:
        return jsonify({'success': False, 'message': 'Geçersiz alan'})
    
    try:
        setattr(step, field, value if value else None)
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)})


@app.route('/step/<int:step_id>/delete', methods=['POST'])
def delete_step(step_id):
    step = Step.query.get_or_404(step_id)
    process_id = step.process_id
    parent_id = step.parent_id
    deleted_order = step.order    
    if step.process.is_started:
        flash('Başlatılmış süreçlerden adım silinemez.', 'error')
        return redirect(url_for('process_detail', process_id=process_id))
    try:        
        for substep in Step.query.filter_by(parent_id=step_id).all():
            StepVariable.query.filter_by(step_id=substep.id).delete()
        StepVariable.query.filter_by(step_id=step_id).delete()
        Step.query.filter_by(parent_id=step_id).delete()        
        db.session.delete(step)        
        remaining_steps = Step.query.filter_by(
            process_id=process_id,
            parent_id=parent_id
        ).filter(Step.order > deleted_order).all()        
        for remaining_step in remaining_steps:
            remaining_step.order -= 1        
        db.session.commit()
        flash('Adım başarıyla silindi', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Adım silinirken hata oluştu: {str(e)}', 'error')    
    return redirect(url_for('process_detail', process_id=process_id))


def reorder_steps(process_id, parent_id=None):
    steps = Step.query.filter_by(
        process_id=process_id,
        parent_id=parent_id
    ).order_by(Step.order).all()    
    for index, step in enumerate(steps, start=1):
        step.order = index        
        reorder_steps(process_id, step.id)


@app.route('/process/<int:process_id>/start', methods=['POST'])
def start_process(process_id):
    process = Process.query.get_or_404(process_id)
    process.is_started = True
    process.started_at = datetime.now()      
    ProcessExecutor.start_process()    
    steps = Step.query.filter_by(process_id=process_id, parent_id=None).all()
    for step in steps:
        if step.status == 'not_started':
            step.status = 'waiting'    
    db.session.commit()
    return redirect(url_for('process_detail', process_id=process_id))


def check_process_status():
    with app.app_context():        
        started_process = Process.query.filter_by(is_started=True).first()
        if started_process:            
            ProcessExecutor.start_process()


@app.before_request
def before_request():
    if not getattr(app, '_got_first_request', False):
        check_process_status()
        app._got_first_request = True


@app.route('/step/<int:step_id>/status', methods=['POST'])
def update_step_status(step_id):
    step = Step.query.get_or_404(step_id)
    new_status = request.form.get('status')    
    if new_status in ['not_started', 'waiting', 'in_progress', 'done']:        
        update_substeps_status(step.id, new_status)        
        step.status = new_status
        
        # Tamamlanma tarihini güncelle
        if new_status == 'done':
            step.completed_at = datetime.now()
        elif step.completed_at is not None:
            step.completed_at = None
            
        db.session.commit()       
        if step.parent_id:
            parent = step.parent
            while parent:
                parent.update_status()
                db.session.commit()
                parent = parent.parent    
    return redirect(url_for('process_detail', process_id=step.process_id))

def update_substeps_status(step_id, new_status):
    # Önce ana adımı al
    parent_step = Step.query.get(step_id)
    if not parent_step:
        return

    # Alt adımları güncelle
    substeps = Step.query.filter_by(parent_id=step_id).all()
    current_time = datetime.now()
    
    for substep in substeps:
        old_status = substep.status
        substep.status = new_status
        
        # Tamamlanma tarihini güncelle
        if new_status == 'done':
            if substep.completed_at is None:
                substep.completed_at = current_time
        elif substep.completed_at is not None:
            substep.completed_at = None
            
        # Alt adımların alt adımlarını güncelle
        update_substeps_status(substep.id, new_status)
    
        db.session.commit()
    
    # Ana adımın durumunu güncelle
    if parent_step.sub_steps:
        parent_step.update_status()
        db.session.commit()
        
        # Üst seviye adımları da güncelle
        current_parent = parent_step.parent
        while current_parent:
            current_parent.update_status()
            db.session.commit()
            current_parent = current_parent.parent


@app.route('/variables/batch-update', methods=['POST'])
def batch_update_variables():
    try:
        step_id = request.form.get('step_id')
        step = Step.query.get_or_404(step_id)   
        for var in step.variables:
            if var.var_type == 'mail_config':
                mail_config = {
                    'to': [addr.strip() for addr in request.form.get(f'mail_to_{var.id}', '').split(',') if addr.strip()],
                    'cc': [addr.strip() for addr in request.form.get(f'mail_cc_{var.id}', '').split(',') if addr.strip()],
                    'subject': request.form.get(f'mail_subject_{var.id}', ''),
                    'body': request.form.get(f'mail_body_{var.id}', ''),
                    'active': request.form.get(f'mail_active_{var.id}') is not None
                }
                var.default_value = json.dumps(mail_config)
            elif var.var_type == 'boolean':
                var.default_value = str(request.form.get(f'variable_{var.id}') == 'true').lower()
            else:
                value = request.form.get(f'variable_{var.id}')
                if value is not None:
                    var.default_value = value            
            for child_var in var.child_variables:
                child_var.default_value = var.default_value        
        db.session.commit()
        flash('Değişkenler başarıyla güncellendi', 'success') 
    except Exception as e:
        db.session.rollback()
        flash(f'Değişkenler güncellenirken hata oluştu: {str(e)}', 'error')    
    return redirect(url_for('process_detail', process_id=step.process_id))


@app.route('/step/<int:step_id>/check-mail-replies', methods=['POST'])
def check_mail_replies(step_id):
    step = Step.query.get_or_404(step_id)
    process = step.process    
    if step.type != 'mail':
        return jsonify({'success': False, 'error': 'Bu adım mail tipi değil'})    
    if not process.is_started:
        return jsonify({'success': False, 'error': 'Süreç henüz başlatılmamış'})    

    mail_variables = StepVariable.query.filter_by(step_id=step_id, var_type='mail_config').all() 
    result = ProcessExecutor.execute_mail_check(start_date=process.started_at)
    received_mails = result['output'] if result['success'] and result['output'] else []
    all_replies_received = True
    has_active_mail = False

    def clean_subject(s):
        return re.sub(r'^(re|cevap|fw|fwd)\s*[:：-]*\s*', '', s, flags=re.IGNORECASE).strip().lower()

    for var in mail_variables:
        try:
            config = json.loads(var.default_value) if var.default_value else {}
            subject = config.get('subject', '')
            active = config.get('active', False)
            if not subject or not active:
                continue
            has_active_mail = True
            if not config.get('sent_at'):
                var.mail_status = 'not_sent'
                all_replies_received = False
                continue
            found_reply = False
            for mail in received_mails:
                if clean_subject(mail['subject']) == clean_subject(subject):
                    mail_received_at = datetime.strptime(mail['received'], '%Y-%m-%d %H:%M:%S')
                    if not MailReply.query.filter_by(variable_id=var.id, subject=mail['subject'], sender=mail['sender'], received_at=mail_received_at).first():
                        reply = MailReply(
                            variable_id=var.id,
                            subject=mail['subject'],
                            sender=mail['sender'],
                            received_at=mail_received_at,
                            original_subject=subject,
                            is_reply=True
                        )
                        db.session.add(reply)
                    var.mail_status = 'received'
                    found_reply = True
                    break
            if not found_reply and config.get('sent_at'):
                var.mail_status = 'waiting'
                all_replies_received = False
        except Exception as e:
            app.logger.error(f"Mail kontrolü sırasında hata: {str(e)}")
            continue
    db.session.commit()
    if has_active_mail and all_replies_received:
        step.status = 'done'
    else:
        step.status = 'waiting'
    db.session.commit()
    # mail_statuses listesini doldur
    response_data = {
        'success': True,
        'output': received_mails,
        'mail_statuses': []
    }
    for var in mail_variables:
        try:
            config = json.loads(var.default_value) if var.default_value else {}
            replies = MailReply.query.filter_by(variable_id=var.id, is_reply=True).all()
            updated_config = config.copy()
            status_data = {
                'variable_id': var.id,
                'subject': updated_config.get('subject', ''),
                'status': var.mail_status,
                'config': updated_config,
                'replies': [{
                    'subject': reply.subject,
                    'sender': reply.sender,
                    'received_at': reply.received_at.strftime('%Y-%m-%d %H:%M:%S')
                } for reply in replies]
            }
            response_data['mail_statuses'].append(status_data)
        except:
            continue
    return jsonify(response_data)


@app.route('/process/<int:process_id>/stop', methods=['POST'])
def stop_process(process_id):
    process = Process.query.get_or_404(process_id)
    process.is_started = False    
    ProcessExecutor.stop_process()    
    db.session.commit()
    return redirect(url_for('process_detail', process_id=process_id))


@app.route('/step/<int:step_id>/mail-config/<int:var_id>/delete', methods=['POST'])
def delete_mail_config(step_id, var_id):
    try:
        step = Step.query.get_or_404(step_id)
        variable = StepVariable.query.get_or_404(var_id)        
        if variable.step_id != step_id:
            error_msg = f"Variable {var_id} does not belong to step {step_id}"
            flash(error_msg, 'error')
            return redirect(url_for('process_detail', process_id=step.process_id))        
        db.session.delete(variable)
        db.session.commit()
        flash('Mail konfigürasyonu başarıyla silindi', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Mail konfigürasyonu silinirken hata oluştu: {str(e)}', 'error')    
    return redirect(url_for('process_detail', process_id=step.process_id))


@app.route('/api/db', methods=['GET'])
def get_db_as_json():
    processes = Process.query.all()
    result = []    
    for process in processes:
        process_data = {
            'id': process.id,
            'name': process.name,
            'description': process.description,
            'created_at': process.created_at.isoformat(),
            'is_started': process.is_started,
            'started_at': process.started_at.isoformat() if process.started_at else None,
            'completion_percentage': process.get_completion_percentage(),
            'status': process.get_status(),
            'steps': []
        }       
        main_steps = Step.query.filter_by(process_id=process.id, parent_id=None).order_by(Step.order).all()
        for step in main_steps:
            step_data = get_step_data_recursive(step)
            process_data['steps'].append(step_data)        
        result.append(process_data)    
    return jsonify(result)

def get_step_data_recursive(step):
    """Adım verilerini alt adımlarıyla birlikte recursive olarak al"""
    step_data = {
        'id': step.id,
        'name': step.name,
        'description': step.description,
        'type': step.type,
        'file_path': step.file_path,
        'order': step.order,
        'responsible': step.responsible,
        'status': step.status,
        'variables': [],
        'sub_steps': []
    }    
    for var in step.variables:
        var_data = {
            'id': var.id,
            'name': var.name,
            'var_type': var.var_type,
            'default_value': var.default_value,
            'scope': var.scope,
            'mail_status': var.mail_status if var.var_type == 'mail_config' else None,
            'parent_variable_id': var.parent_variable_id,
            'mail_replies': []
        }        
        if var.var_type == 'mail_config':
            replies = MailReply.query.filter_by(
                variable_id=var.id,
                is_reply=True
            ).order_by(MailReply.received_at.asc()).all()            
            var_data['mail_replies'] = [{
                'id': reply.id,
                'subject': reply.subject,
                'sender': reply.sender,
                'received_at': reply.received_at.isoformat(),
                'original_subject': reply.original_subject
            } for reply in replies]
            try:
                config = json.loads(var.default_value) if var.default_value else {}
                var_data['mail_config'] = {
                    'to': config.get('to', []),
                    'cc': config.get('cc', []),
                    'subject': config.get('subject', ''),
                    'body': config.get('body', ''),
                    'active': config.get('active', False)
                }
            except:
                var_data['mail_config'] = None
        step_data['variables'].append(var_data)    
    for sub_step in step.sub_steps:
        sub_step_data = get_step_data_recursive(sub_step)
        step_data['sub_steps'].append(sub_step_data)    
    return step_data

@app.route('/debug/step/<int:step_id>/variables')
def debug_step_variables(step_id):
    step = Step.query.get_or_404(step_id)
    variables = StepVariable.query.filter_by(step_id=step_id).all()
    result = []
    for var in variables:
        result.append({
            'id': var.id,
            'name': var.name,
            'var_type': var.var_type,
            'default_value': var.default_value,
            'scope': var.scope,
            'parent_variable_id': var.parent_variable_id
        })
    return jsonify(result)


@app.route('/process/<int:process_id>/copy', methods=['POST'])
def copy_process(process_id):
    try:
        original_process = Process.query.get_or_404(process_id)
        new_process = Process(
            name=f"{original_process.name} (Kopya)",
            description=original_process.description,
            category_id=original_process.category_id,
            year=original_process.year,
            is_started=False,
            started_at=None
        )
        db.session.add(new_process)
        db.session.flush()  
        step_id_map = {}
        main_steps = Step.query.filter_by(process_id=process_id, parent_id=None).order_by(Step.order).all()
        for main_step in main_steps:
            new_main_step = copy_step(main_step, new_process.id, None)
            step_id_map[main_step.id] = new_main_step.id            
            copy_substeps_recursive(main_step.id, new_main_step.id, new_process.id, step_id_map)        
        MailReply.query.filter(
            MailReply.variable_id.in_(
                db.session.query(StepVariable.id)
                .filter(StepVariable.step_id.in_(
                    db.session.query(Step.id)
                    .filter(Step.process_id == new_process.id)
                ))
            )
        ).delete(synchronize_session=False)        
        db.session.commit()
        flash('Süreç başarıyla kopyalandı', 'success')

        # Kopyalama sonrası yönlendirme
        if new_process.category_id:
            return redirect(url_for('category_processes', category_id=new_process.category_id, year=new_process.year))
        else:
            return redirect(url_for('uncategorized_processes', year=new_process.year))
                
    except Exception as e:
        db.session.rollback()
        flash(f'Süreç kopyalanırken hata oluştu: {str(e)}', 'error')    
    return redirect(url_for('index'))

def copy_step(original_step, new_process_id, new_parent_id):    
    new_step = Step(
        name=original_step.name,
        description=original_step.description,
        type=original_step.type,
        file_path=original_step.file_path,
        order=original_step.order,
        parent_id=new_parent_id,
        process_id=new_process_id,
        responsible=original_step.responsible,
        status='not_started'
    )
    db.session.add(new_step)
    db.session.flush()      
    for var in original_step.variables:
        new_var = StepVariable(
            step_id=new_step.id,
            name=var.name,
            var_type=var.var_type,
            default_value=var.default_value,
            scope=var.scope,
            mail_status='waiting' if var.var_type == 'mail_config' else None
        )
        db.session.add(new_var)        
        if var.var_type == 'mail_config':
            try:
                config = json.loads(var.default_value) if var.default_value else {}                
                if 'sent_at' in config:
                    del config['sent_at']
                new_var.default_value = json.dumps(config)
            except:
                pass    
    return new_step

def copy_substeps_recursive(original_parent_id, new_parent_id, new_process_id, step_id_map):
    substeps = Step.query.filter_by(parent_id=original_parent_id).order_by(Step.order).all()    
    for substep in substeps:
        new_substep = copy_step(substep, new_process_id, new_parent_id)
        step_id_map[substep.id] = new_substep.id         
        copy_substeps_recursive(substep.id, new_substep.id, new_process_id, step_id_map)


@app.route('/process/<int:process_id>/update', methods=['POST'])
def update_process(process_id):
    try:
        process = Process.query.get_or_404(process_id)
        field = request.form.get('field')
        value = request.form.get('value')
        current_version = request.form.get('version', type=int)

        # Versiyon kontrolü
        if current_version and current_version != process.version:
            return jsonify({
                'success': False,
                'error': 'Bu kayıt başka bir kullanıcı tarafından güncellenmiş. Lütfen sayfayı yenileyip tekrar deneyin.'
            })

        if field == 'name':
            process.name = value
        elif field == 'description':
            process.description = value

        process.version += 1  # Versiyon numarasını artır
        db.session.commit()
        
        return jsonify({
            'success': True,
            'new_version': process.version
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)})
    

@app.route('/api/process/<int:process_id>/flowchart')
def get_process_flowchart(process_id):
    process = Process.query.get_or_404(process_id)
    main_steps = Step.query.filter_by(process_id=process_id, parent_id=None).order_by(Step.order).all()
    
    nodes = []
    edges = []
    processed_ids = set()
    
    # Ana süreç düğümü
    process_node_id = f'process_{process.id}'
    nodes.append({
        'id': process_node_id,
        'label': process.name,
        'title': process.description or '',
        'group': 'main',
        'level': 0
    })
    processed_ids.add(process_node_id)
    
    # Ana adımlar
    for main_step in main_steps:
        main_step_id = f'step_{main_step.id}'
        if main_step_id not in processed_ids:
            nodes.append({
                'id': main_step_id,
                'label': main_step.name,
                'title': main_step.description or '',
                'group': main_step.type,
                'level': 1
            })
            processed_ids.add(main_step_id)
            
            # Ana süreç ile ana adım arasındaki bağlantı
            edges.append({
                'from': process_node_id,
                'to': main_step_id
            })
        
        # Alt adımlar
        substeps = Step.query.filter_by(parent_id=main_step.id).order_by(Step.order).all()
        for substep in substeps:
            substep_id = f'step_{substep.id}'
            if substep_id not in processed_ids:
                nodes.append({
                    'id': substep_id,
                    'label': substep.name,
                    'title': substep.description or '',
                    'group': substep.type,
                    'level': 2
                })
                processed_ids.add(substep_id)
            
            # Ana adım ile alt adım arasındaki bağlantı
            edges.append({
                'from': main_step_id,
                'to': substep_id
            })
            
            # Alt-alt adımlar
            subsubsteps = Step.query.filter_by(parent_id=substep.id).order_by(Step.order).all()
            for subsubstep in subsubsteps:
                subsubstep_id = f'step_{subsubstep.id}'
                if subsubstep_id not in processed_ids:
                    nodes.append({
                        'id': subsubstep_id,
                        'label': subsubstep.name,
                        'title': subsubstep.description or '',
                        'group': subsubstep.type,
                        'level': 3
                    })
                    processed_ids.add(subsubstep_id)
                
                # Alt adım ile alt-alt adım arasındaki bağlantı
                edges.append({
                    'from': substep_id,
                    'to': subsubstep_id
                })
    
    return jsonify({
        'nodes': nodes,
        'edges': edges
    })

@app.route('/api/calendar/completed-steps')
def get_completed_steps():
    # URL'den sorumlu kişi ve kategori parametrelerini al
    responsible = request.args.get('responsible', None)
    category_id = request.args.get('category_id', None)
    
    # Base query - hem tamamlanmış hem de deadline'ı olan adımları al
    query = Step.query.filter(
        Step.parent_id.is_(None),  # Ana adımları filtrele
        db.or_(
            Step.completed_at.isnot(None),  # Tamamlanmış adımlar
            Step.deadline.isnot(None)  # Deadline'ı olan adımlar
        )
    ).join(Process, Step.process_id == Process.id)  # Process tablosuyla join
    
    # Eğer sorumlu kişi filtresi varsa, query'e ekle
    if responsible:
        query = query.filter(Step.responsible == responsible)
        
    # Eğer kategori filtresi varsa, query'e ekle
    if category_id:
        query = query.filter(Process.category_id == category_id)
    
    steps = query.all()
    
    events = []
    
    for step in steps:
        # Ana adımın adını ve süreç adını birleştir
        step_title = f"{step.process.name} - {step.name}"
        
        # Eğer adım tamamlanmışsa
        if step.completed_at:
            completion_time = step.completed_at
            event = {
                'id': step.id,
                'title': step_title,
                'start': completion_time.strftime('%Y-%m-%dT%H:%M:%S'),
                'display': 'block',
                'allDay': False,
                'backgroundColor': 'rgba(40, 167, 69, 0.3)',  # Yeşil renk yarı saydam
                'borderColor': '#28a745',  # Yeşil renk
                'classNames': ['completed-event', 'striped-background'],
                'extendedProps': {
                    'processId': step.process_id,
                    'processName': step.process.name,
                    'stepType': step.type,
                    'description': step.description or '',
                    'responsible': step.responsible or '',
                    'completionTime': completion_time.strftime('%H:%M'),
                    'completionDate': completion_time.strftime('%d.%m.%Y %H:%M'),
                    'status': 'completed',
                    'categoryId': step.process.category_id,
                    'categoryName': step.process.category.name if step.process.category else 'Kategorisiz'
                }
            }
            events.append(event)
        
        # Eğer deadline varsa ve adım tamamlanmamışsa
        if step.deadline and not step.completed_at:
            now = datetime.now()
            is_overdue = step.deadline < now
            
            event = {
                'id': step.id,
                'title': step_title,
                'start': step.deadline.strftime('%Y-%m-%dT%H:%M:%S'),
                'display': 'block',
                'allDay': False,
                'backgroundColor': 'rgba(220, 53, 69, 0.3)' if is_overdue else 'rgba(255, 193, 7, 0.3)',  # Gecikmiş: kırmızı, Normal: sarı
                'borderColor': '#dc3545' if is_overdue else '#ffc107',  # Gecikmiş: kırmızı, Normal: sarı
                'classNames': ['deadline-event', 'striped-background', 'overdue-event' if is_overdue else ''],
                'extendedProps': {
                    'processId': step.process_id,
                    'processName': step.process.name,
                    'stepType': step.type,
                    'description': step.description or '',
                    'responsible': step.responsible or '',
                    'deadline': step.deadline.strftime('%d.%m.%Y %H:%M'),
                    'status': 'overdue' if is_overdue else 'pending',
                    'categoryId': step.process.category_id,
                    'categoryName': step.process.category.name if step.process.category else 'Kategorisiz'
                }
            }
            events.append(event)
    
    return jsonify(events)

@app.route('/step/<int:step_id>/update_deadline', methods=['POST'])
def update_step_deadline(step_id):
    step = Step.query.get_or_404(step_id)
    deadline_str = request.form.get('deadline')
    
    try:
        if deadline_str:
            deadline = datetime.strptime(deadline_str, '%Y-%m-%dT%H:%M')
            step.deadline = deadline
        else:
            step.deadline = None
            
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/calendar/responsibles')
def get_responsibles():
    # Tüm sorumlu kişileri al (tekrarsız)
    responsibles = db.session.query(Step.responsible)\
        .filter(Step.responsible.isnot(None))\
        .distinct()\
        .order_by(Step.responsible)\
        .all()
    
    # Liste formatına çevir
    responsible_list = [r[0] for r in responsibles if r[0]]  # Boş değerleri filtrele
    
    return jsonify(responsible_list)

@app.route('/process/calendar')
def process_calendar():
    return render_template('process_calendar.html')

@app.route('/process/<int:process_id>/stats')
def process_stats(process_id):
    process = Process.query.get_or_404(process_id)
    steps = Step.query.filter_by(process_id=process_id).all()
    total_steps = len(steps)
    completed_steps = sum(1 for s in steps if s.status == 'done')
    # Aktif sorumlular
    responsibles = sorted(set(s.responsible for s in steps if s.responsible))
    active_responsibles = len(responsibles)

    # Completion data for doughnut chart: [done, in_progress, waiting, not_started]
    status_map = {'done': 0, 'in_progress': 1, 'waiting': 2, 'not_started': 3}
    completion_data = [0, 0, 0, 0]
    for s in steps:
        idx = status_map.get(s.status, 3)
        completion_data[idx] += 1

    # Step types for bar chart
    type_map = {}
    for s in steps:
        key = s.type or 'Bilinmiyor'
        if key not in type_map:
            type_map[key] = 0
        type_map[key] += 1
    step_types = list(type_map.keys())
    step_type_counts = list(type_map.values())

    # Timeline chart: completed steps per hour
    timeline_counter = Counter()
    for s in steps:
        if s.completed_at:
            date_str = s.completed_at.strftime('%Y-%m-%d %H:00')
            timeline_counter[date_str] += 1
    timeline_dates = sorted(timeline_counter.keys())
    timeline_counts = []
    cumulative = 0
    for d in timeline_dates:
        cumulative += timeline_counter[d]
        timeline_counts.append(cumulative)

    return render_template(
        'process_stats.html',
        process=process,
        total_steps=total_steps,
        completed_steps=completed_steps,
        active_responsibles=active_responsibles,
        responsibles=responsibles,
        completion_data=completion_data,
        step_types=step_types,
        step_type_counts=step_type_counts,
        timeline_dates=timeline_dates,
        timeline_counts=timeline_counts
    )

@app.route('/category/new', methods=['GET', 'POST'])
def new_category():
    if request.method == 'POST':
        name = request.form.get('name')
        description = request.form.get('description')
        
        if name:
            category = ProcessCategory(name=name, description=description)
            db.session.add(category)
            db.session.commit()
            flash('Kategori başarıyla oluşturuldu', 'success')
            return redirect(url_for('index'))
    
    return render_template('new_category.html')

@app.route('/category/<int:category_id>/edit', methods=['GET', 'POST'])
def edit_category(category_id):
    category = ProcessCategory.query.get_or_404(category_id)
    
    if request.method == 'POST':
        name = request.form.get('name')
        description = request.form.get('description')
        
        if name:
            category.name = name
            category.description = description
            db.session.commit()
            flash('Kategori başarıyla güncellendi', 'success')
            return redirect(url_for('category_years', category_id=category_id))
    
    return render_template('edit_category.html', category=category)

@app.route('/process/<int:process_id>/update_category', methods=['POST'])
def update_process_category(process_id):
    process = Process.query.get_or_404(process_id)
    old_category_id = process.category_id
    old_year = process.year
    
    category_id = request.form.get('category_id')
    year = request.form.get('year', type=int)
    
    try:
        process.category_id = category_id if category_id else None
        if year:
            process.year = year
        db.session.commit()
        flash('Süreç başarıyla güncellendi', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Süreç güncellenirken hata oluştu: {str(e)}', 'error')
    
    # Eğer kategori değiştiyse, yeni kategoriye yönlendir
    if category_id != old_category_id or year != old_year:
        if category_id:
            return redirect(url_for('category_processes', category_id=category_id, year=year))
        else:
            return redirect(url_for('uncategorized_processes', year=year))
    
    # Kategori değişmediyse mevcut sayfada kal
    if process.category_id:
        return redirect(url_for('category_processes', category_id=process.category_id, year=process.year))
    else:
        return redirect(url_for('uncategorized_processes', year=process.year))

@app.route('/api/calendar/categories')
def get_calendar_categories():
    # Tüm kategorileri al
    categories = ProcessCategory.query.order_by(ProcessCategory.name).all()
    
    # Liste formatına çevir
    category_list = [{'id': cat.id, 'name': cat.name} for cat in categories]
    
    # Kategorisiz seçeneğini ekle
    category_list.insert(0, {'id': '', 'name': 'Kategorisiz'})
    
    return jsonify(category_list)

@app.route('/api/responsible/<responsible>/steps')
def get_responsible_steps(responsible):
    # Sorumluya ait tüm adımları al
    steps = Step.query.filter_by(responsible=responsible).all()
    
    # İstatistikleri hesapla
    total_steps = len(steps)
    completed_steps = sum(1 for step in steps if step.status == 'done')
    completion_rate = int((completed_steps / total_steps * 100) if total_steps > 0 else 0)
    
    # Adım detaylarını hazırla
    step_details = []
    for step in steps:
        process = Process.query.get(step.process_id)
        step_details.append({
            'id': step.id,
            'process_id': step.process_id,  # Süreç ID'sini ekle
            'name': step.name,
            'status': step.status,
            'process_name': process.name if process else 'Bilinmeyen Süreç',
            'completed_at': step.completed_at.strftime('%d.%m.%Y %H:%M') if step.completed_at else None
        })
    
    # Adımları duruma göre sırala: done > in_progress > waiting > not_started
    status_order = {'done': 0, 'in_progress': 1, 'waiting': 2, 'not_started': 3}
    step_details.sort(key=lambda x: (status_order[x['status']], x['name']))
    
    return jsonify({
        'total_steps': total_steps,
        'completed_steps': completed_steps,
        'completion_rate': completion_rate,
        'steps': step_details
    })

@app.route('/excel-import')
def excel_import():
    return render_template('excel_import.html')

@app.route('/api/oracle/tables')
def get_oracle_tables():
    try:
        # Oracle bağlantı bilgilerini al
        username = app.config.get('ORACLE_USERNAME')
        password = app.config.get('ORACLE_PASSWORD')
        dsn = app.config.get('ORACLE_DSN')
        
        # Oracle'a bağlan
        connection = oracledb.connect(user=username, password=password, dsn=dsn)
        cursor = connection.cursor()
        
        # Kullanıcının erişebildiği tabloları al
        cursor.execute("""
            SELECT table_name 
            FROM user_tables 
            ORDER BY table_name
        """)
        
        tables = [row[0] for row in cursor.fetchall()]
        
        cursor.close()
        connection.close()
        
        return jsonify({'success': True, 'tables': tables})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/excel/sheets', methods=['POST'])
def get_excel_sheets():
    try:
        file_input_mode = request.form.get('file_input_mode')
        
        if file_input_mode == 'select':
            if 'file' not in request.files:
                return jsonify({'success': False, 'error': 'Dosya yüklenmedi'})
            file = request.files['file']
            df = pd.ExcelFile(file)
        else:  # path mode
            file_path = request.form.get('file_path')
            if not file_path:
                return jsonify({'success': False, 'error': 'Dosya yolu belirtilmedi'})
            if not os.path.exists(file_path):
                return jsonify({'success': False, 'error': 'Dosya bulunamadı'})
            df = pd.ExcelFile(file_path)
        
        sheets = df.sheet_names
        return jsonify({'success': True, 'sheets': sheets})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

def convert_to_oracle_column_name(column_name):
    """
    Excel sütun isimlerini Oracle uyumlu formata dönüştürür.
    - Türkçe karakterleri değiştirir
    - Boşlukları alt çizgi ile değiştirir
    - Özel karakterleri kaldırır
    - Tüm harfleri büyük yapar
    """
    # Türkçe karakter dönüşümü
    tr_chars = {
        'ı': 'I', 'ğ': 'G', 'ü': 'U', 'ş': 'S', 'ö': 'O', 'ç': 'C',
        'İ': 'I', 'Ğ': 'G', 'Ü': 'U', 'Ş': 'S', 'Ö': 'O', 'Ç': 'C',
        'i': 'I', 'g': 'G', 'u': 'U', 's': 'S', 'o': 'O', 'c': 'C'
    }
    
    # Sütun ismini dönüştür
    column = str(column_name)
    
    # Türkçe karakterleri değiştir
    for tr_char, eng_char in tr_chars.items():
        column = column.replace(tr_char, eng_char)
    
    # Boşlukları ve özel karakterleri alt çizgi ile değiştir
    column = re.sub(r'[^a-zA-Z0-9]', '_', column)
    
    # Birden fazla alt çizgiyi tek alt çizgiye dönüştür
    column = re.sub(r'_+', '_', column)
    
    # Başındaki ve sonundaki alt çizgileri kaldır
    column = column.strip('_')
    
    # Tüm harfleri büyük yap
    column = column.upper()
    
    # Oracle'da geçerli bir sütun ismi oluştur
    if not column:
        column = 'COLUMN_' + str(hash(str(column_name)) % 10000)
    elif column[0].isdigit():
        column = 'COLUMN_' + column
    
    return column

@app.route('/api/excel/columns', methods=['POST'])
def get_excel_columns():
    try:
        file_input_mode = request.form.get('file_input_mode')
        sheet_name = request.form.get('sheet_name')
        
        if not sheet_name:
            return jsonify({'success': False, 'error': 'Sayfa adı gerekli'})
        
        # Excel dosyasını oku
        if file_input_mode == 'select':
            if 'file' not in request.files:
                return jsonify({'success': False, 'error': 'Dosya yüklenmedi'})
            file = request.files['file']
            df = pd.read_excel(file, sheet_name=sheet_name)
        else:  # path mode
            file_path = request.form.get('file_path')
            if not file_path:
                return jsonify({'success': False, 'error': 'Dosya yolu belirtilmedi'})
            if not os.path.exists(file_path):
                return jsonify({'success': False, 'error': 'Dosya bulunamadı'})
            df = pd.read_excel(file_path, sheet_name=sheet_name)
        
        # Sütun bilgilerini hazırla
        columns = df.columns.tolist()
        column_types = {}
        
        for col in columns:
            dtype = str(df[col].dtype)
            if 'int' in dtype or 'float' in dtype:
                column_types[col] = 'number'
            elif 'datetime' in dtype:
                column_types[col] = 'date'
            else:
                column_types[col] = 'string'
        
        return jsonify({
            'success': True,
            'columns': columns,
            'column_types': column_types
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/oracle/columns/<table_name>')
def get_oracle_columns(table_name):
    try:
        # Oracle bağlantı bilgilerini al
        username = app.config.get('ORACLE_USERNAME')
        password = app.config.get('ORACLE_PASSWORD')
        dsn = app.config.get('ORACLE_DSN')
        
        # Oracle'a bağlan
        connection = oracledb.connect(user=username, password=password, dsn=dsn)
        cursor = connection.cursor()
        
        # Tablo yapısını al
        cursor.execute("""
            SELECT column_name, data_type, data_length, data_precision, data_scale
            FROM user_tab_columns 
            WHERE table_name = :1
            ORDER BY column_id
        """, [table_name])
        
        columns = []
        for row in cursor.fetchall():
            col_name, data_type, data_length, data_precision, data_scale = row
            
            # Veri tipini formatla
            if data_type == 'NUMBER':
                if data_scale == 0:
                    col_type = 'INTEGER'
                else:
                    col_type = f'NUMBER({data_precision},{data_scale})'
            elif data_type == 'VARCHAR2':
                col_type = f'VARCHAR2({data_length})'
            else:
                col_type = data_type
            
            columns.append({
                'name': col_name,
                'type': col_type
            })
        
        cursor.close()
        connection.close()
        
        return jsonify({
            'success': True,
            'columns': columns
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/excel/import', methods=['POST'])
def import_excel():
    try:
        file_input_mode = request.form.get('file_input_mode')
        sheet_name = request.form.get('sheet_name')
        create_new_table = request.form.get('create_new_table') == 'true'
        column_mappings = json.loads(request.form.get('column_mappings', '[]'))
        
        # Dosya kontrolü
        if file_input_mode == 'select':
            if 'file' not in request.files:
                return jsonify({'success': False, 'error': 'Dosya yüklenmedi'})
            file = request.files['file']
            df = pd.read_excel(file, sheet_name=sheet_name)
        else:  # path mode
            file_path = request.form.get('file_path')
            if not file_path:
                return jsonify({'success': False, 'error': 'Dosya yolu belirtilmedi'})
            if not os.path.exists(file_path):
                return jsonify({'success': False, 'error': 'Dosya bulunamadı'})
            df = pd.read_excel(file_path, sheet_name=sheet_name)
        
        if not sheet_name:
            return jsonify({'success': False, 'error': 'Sayfa adı gerekli'})
        
        # Oracle bağlantı bilgilerini al
        username = app.config.get('ORACLE_USERNAME')
        password = app.config.get('ORACLE_PASSWORD')
        dsn = app.config.get('ORACLE_DSN')
        
        # Oracle'a bağlan
        connection = oracledb.connect(user=username, password=password, dsn=dsn)
        cursor = connection.cursor()
        
        if create_new_table:
            # Yeni tablo adını al
            new_table_name = request.form.get('new_table_name')
            if not new_table_name:
                return jsonify({'success': False, 'error': 'Yeni tablo adı gerekli'})
            
            # Tablo adını Oracle uyumlu formata dönüştür
            new_table_name = convert_to_oracle_column_name(new_table_name)
            
            # CREATE TABLE sorgusunu oluştur
            create_table_query = f"""
            CREATE TABLE {new_table_name} (
                {', '.join(f'"{mapping["oracle_column"]}" {mapping["oracle_type"]}' for mapping in column_mappings)}
            )
            """
            
            try:
                cursor.execute(create_table_query)
                connection.commit()
            except oracledb.DatabaseError as e:
                error, = e.args
                return jsonify({'success': False, 'error': f'Tablo oluşturulurken hata: {error.message}'})
            
            table_name = new_table_name
        else:
            table_name = request.form.get('table_name')
            if not table_name:
                return jsonify({'success': False, 'error': 'Hedef tablo adı gerekli'})
            
            # Tablo yapısını al
            cursor.execute(f"SELECT column_name FROM user_tab_columns WHERE table_name = '{table_name}'")
            oracle_columns = [row[0] for row in cursor.fetchall()]
            
            # Eşleşen sütunları kontrol et
            mapping_columns = [mapping['oracle_column'] for mapping in column_mappings]
            invalid_columns = [col for col in mapping_columns if col not in oracle_columns]
            
            if invalid_columns:
                return jsonify({
                    'success': False,
                    'error': f'Geçersiz sütun isimleri: {", ".join(invalid_columns)}'
                })
            
            # İçe aktarma modunu kontrol et
            import_mode = request.form.get('import_mode', 'append')
            if import_mode == 'replace':
                try:
                    # Tabloyu temizle
                    cursor.execute(f"TRUNCATE TABLE {table_name}")
                    connection.commit()
                except oracledb.DatabaseError as e:
                    error, = e.args
                    return jsonify({
                        'success': False,
                        'error': f'Tablo temizlenirken hata: {error.message}'
                })
        
        # Verileri Oracle'a aktar
        for _, row in df.iterrows():
            values = []
            columns = []
            
            for mapping in column_mappings:
                excel_col = mapping['excel_column']
                oracle_col = mapping['oracle_column']
                oracle_type = mapping['oracle_type'].upper()
                
                if excel_col in df.columns:
                    value = row[excel_col]
                    
                    # Veri tipine göre dönüşüm yap
                    try:
                        if 'NUMBER' in oracle_type or 'INTEGER' in oracle_type or 'FLOAT' in oracle_type:
                            # Sayısal alanlar için
                            if pd.isna(value):
                                value = 0
                            else:
                                value = float(value)
                        elif 'DATE' in oracle_type or 'TIMESTAMP' in oracle_type:
                            # Tarih alanları için
                            if pd.isna(value):
                                value = None
                            elif isinstance(value, (pd.Timestamp, datetime)):
                                value = value
                            else:
                                value = None
                        else:
                            # Karakter alanları için
                            if pd.isna(value):
                                value = None
                            else:
                                value = str(value)
                    except (ValueError, TypeError):
                        # Dönüşüm hatası durumunda
                        if 'NUMBER' in oracle_type or 'INTEGER' in oracle_type or 'FLOAT' in oracle_type:
                            value = 0
                        else:
                            value = None
                    
                    values.append(value)
                    columns.append(oracle_col)
            
            placeholders = ','.join([':' + str(i+1) for i in range(len(columns))])
            quoted_columns = [f'"{col}"' for col in columns]
            insert_query = f"INSERT INTO {table_name} ({','.join(quoted_columns)}) VALUES ({placeholders})"
            
            try:
                cursor.execute(insert_query, values)
            except oracledb.DatabaseError as e:
                error, = e.args
                return jsonify({
                    'success': False, 
                    'error': f'Veri aktarımı sırasında hata: {error.message}. Sütun: {excel_col}, Değer: {value}'
                })
        
        connection.commit()
        cursor.close()
        connection.close()
        
        # Sütun eşleştirme bilgilerini hazırla
        column_mapping = {mapping['excel_column']: mapping['oracle_column'] for mapping in column_mappings}
        
        return jsonify({
            'success': True,
            'message': f'{len(df)} satır başarıyla içe aktarıldı' + 
                      (f' ve {table_name} tablosu oluşturuldu' if create_new_table else ''),
            'column_mapping': column_mapping
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

# Import Process modeli
class ImportProcess(db.Model):
    __tablename__ = 'import_process'  # Tablo adını açıkça belirt
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    sheet_name = db.Column(db.String(100), nullable=False)
    create_new_table = db.Column(db.Boolean, default=False)
    table_name = db.Column(db.String(100), nullable=False)
    column_mappings = db.Column(db.Text, nullable=False)  # JSON olarak saklanacak
    import_mode = db.Column(db.String(20), default='append')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_used_at = db.Column(db.DateTime)

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'file_path': self.file_path,
            'sheet_name': self.sheet_name,
            'create_new_table': self.create_new_table,
            'table_name': self.table_name,
            'column_mappings': json.loads(self.column_mappings),
            'import_mode': self.import_mode,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'last_used_at': self.last_used_at.isoformat() if self.last_used_at else None
        }

# Veritabanını güncelle
def create_import_process_table():
    with app.app_context():
        inspector = inspect(db.engine)
        # Tablo zaten varsa oluşturmayı atla
        if not inspector.has_table('import_process'):
            db.create_all()
            print("import_process tablosu oluşturuldu")
        else:
            print("import_process tablosu zaten mevcut")

create_import_process_table()

with app.app_context():
    db.create_all()

# Import Process endpoints
@app.route('/api/import-processes', methods=['GET'])
def get_import_processes():
    processes = ImportProcess.query.order_by(ImportProcess.created_at.desc()).all()
    return jsonify({
        'success': True,
        'processes': [process.to_dict() for process in processes]
    })

@app.route('/api/import-processes', methods=['POST'])
def save_import_process():
    try:
        data = request.json
        if not data.get('name'):
            return jsonify({'success': False, 'error': 'İşlem adı gerekli'})

        process = ImportProcess(
            name=data['name'],
            file_path=data['file_path'],
            sheet_name=data['sheet_name'],
            create_new_table=data['create_new_table'],
            table_name=data['table_name'],
            column_mappings=json.dumps(data['column_mappings']),
            import_mode=data.get('import_mode', 'append')
        )
        db.session.add(process)
        db.session.commit()

        return jsonify({
            'success': True,
            'message': 'İşlem başarıyla kaydedildi',
            'process': process.to_dict()
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/import-processes/<int:process_id>', methods=['GET'])
def get_import_process(process_id):
    process = ImportProcess.query.get_or_404(process_id)
    return jsonify({
        'success': True,
        'process': process.to_dict()
    })

@app.route('/api/import-processes/<int:process_id>', methods=['DELETE'])
def delete_import_process(process_id):
    process = ImportProcess.query.get_or_404(process_id)
    db.session.delete(process)
    db.session.commit()
    return jsonify({
        'success': True,
        'message': 'İşlem başarıyla silindi'
    })

@app.route('/api/import-processes/<int:process_id>/execute', methods=['POST'])
def execute_import_process(process_id):
    try:
        process = ImportProcess.query.get_or_404(process_id)
        
        # Dosyanın varlığını kontrol et
        if not os.path.exists(process.file_path):
            return jsonify({
                'success': False,
                'error': 'Dosya bulunamadı: ' + process.file_path
            })
        
        # Import işlemini gerçekleştir
        df = pd.read_excel(process.file_path, sheet_name=process.sheet_name)
        column_mappings = json.loads(process.column_mappings)
        
        # Oracle bağlantısı
        connection = oracledb.connect(
            user=app.config['ORACLE_USERNAME'],
            password=app.config['ORACLE_PASSWORD'],
            dsn=app.config['ORACLE_DSN']
        )
        cursor = connection.cursor()
        
        # Replace modunda tabloyu temizle
        if process.import_mode == 'replace' and not process.create_new_table:
            cursor.execute(f"TRUNCATE TABLE {process.table_name}")
            connection.commit()
        
        # Yeni tablo oluştur
        if process.create_new_table:
            create_table_query = f"""
            CREATE TABLE {process.table_name} (
                {', '.join(f'"{mapping["oracle_column"]}" {mapping["oracle_type"]}' for mapping in column_mappings)}
            )
            """
            cursor.execute(create_table_query)
            connection.commit()
        
        # Verileri Oracle'a aktar
        for _, row in df.iterrows():
            values = []
            columns = []
            
            for mapping in column_mappings:
                excel_col = mapping['excel_column']
                oracle_col = mapping['oracle_column']
                oracle_type = mapping['oracle_type'].upper()
                
                if excel_col in df.columns:
                    value = row[excel_col]
                    
                    # Veri tipi dönüşümü
                    if 'NUMBER' in oracle_type or 'INTEGER' in oracle_type or 'FLOAT' in oracle_type:
                        value = float(value) if pd.notna(value) else 0
                    elif 'DATE' in oracle_type or 'TIMESTAMP' in oracle_type:
                        value = value if pd.notna(value) and isinstance(value, (pd.Timestamp, datetime)) else None
                    else:
                        value = str(value) if pd.notna(value) else None
                    
                    values.append(value)
                    columns.append(oracle_col)
            
            placeholders = ','.join([':' + str(i+1) for i in range(len(columns))])
            quoted_columns = [f'"{col}"' for col in columns]
            insert_query = f"INSERT INTO {process.table_name} ({','.join(quoted_columns)}) VALUES ({placeholders})"
            
            try:
                cursor.execute(insert_query, values)
            except oracledb.DatabaseError as e:
                error, = e.args
                return jsonify({
                    'success': False, 
                    'error': f'Veri aktarımı sırasında hata: {error.message}. Sütun: {excel_col}, Değer: {value}'
                })
        
        connection.commit()
        cursor.close()
        connection.close()
        
        # Son kullanım zamanını güncelle
        process.last_used_at = datetime.utcnow()
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'{len(df)} satır başarıyla içe aktarıldı'
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

if __name__ == '__main__':
    with app.app_context():
        # Sadece tabloları oluştur, silme işlemini kaldır
        db.create_all()
    app.run(debug=True, port=5001) 