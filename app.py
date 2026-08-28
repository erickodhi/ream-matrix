import csv
import io
from datetime import datetime
from flask import Response, Flask, render_template, redirect, url_for, request, flash, session
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secure-secret-key-here'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///ream_matrix.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# User Model
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(50), nullable=False) # 'Admin', 'HOI', 'Collection'

# System Settings Model for Global Parameters
class SystemSetting(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(50), unique=True, nullable=False)
    value = db.Column(db.String(50), nullable=False)

# Student Model
class Student(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    admin_no = db.Column(db.String(50), nullable=False) 
    full_name = db.Column(db.String(150), nullable=False)
    form_grade = db.Column(db.String(50), nullable=False)
    stream = db.Column(db.String(50), nullable=False)
    gender = db.Column(db.String(20), nullable=False)
    expected_reams = db.Column(db.Integer, default=1, nullable=False)
    
    academic_year = db.Column(db.String(20), nullable=False) # e.g. "2026"
    term = db.Column(db.Integer, nullable=False, default=1) # 1, 2, or 3
    
    term_1_status = db.Column(db.String(30), default='Pending') # Pending, Cleared, Exempted, N/A
    term_2_status = db.Column(db.String(30), default='Pending')
    term_3_status = db.Column(db.String(30), default='Pending')
    ream_owed = db.Column(db.Integer, default=3) # e.g., 1 ream per term

# Ream Store Model for Store Inventory Balance
class ReamStore(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    reams_balance = db.Column(db.Integer, nullable=False, default=0)
    loose_sheets_balance = db.Column(db.Integer, nullable=False, default=0)

# Audit Log Model for Collection Desk Actions
class CollectionAudit(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    collector_username = db.Column(db.String(100), nullable=False)
    student_admin_no = db.Column(db.String(50), nullable=False)
    student_name = db.Column(db.String(150), nullable=False)
    academic_year = db.Column(db.String(20), nullable=False)
    term = db.Column(db.String(20), nullable=False)
    action = db.Column(db.String(30), nullable=False) # 'Cleared' or 'Reverted'

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

# Helper function to get global system settings anywhere in the app
def get_system_context():
    y = SystemSetting.query.filter_by(key='active_year').first()
    t = SystemSetting.query.filter_by(key='active_term').first()
    return {
        'active_year': y.value if y else '2026',
        'active_term': t.value if t else '1'
    }

# Create Database Tables and Default Records on Startup
with app.app_context():
    db.create_all()
    if not User.query.filter_by(role='Admin').first():
        hashed_pw = generate_password_hash('admin123', method='pbkdf2:sha256')
        admin_user = User(username='admin', password=hashed_pw, role='Admin')
        db.session.add(admin_user)
        db.session.commit()
        
    if not SystemSetting.query.filter_by(key='active_year').first():
        db.session.add(SystemSetting(key='active_year', value='2026'))
    if not SystemSetting.query.filter_by(key='active_term').first():
        db.session.add(SystemSetting(key='active_term', value='1'))
        
    if not ReamStore.query.first():
        db.session.add(ReamStore(reams_balance=100, loose_sheets_balance=0))
        
    db.session.commit()

# Routes
@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        user = User.query.filter_by(username=username).first()
        
        if user and check_password_hash(user.password, password):
            login_user(user)
            if user.role == 'Admin':
                return redirect(url_for('admin_page'))
            elif user.role == 'HOI':
                return redirect(url_for('hoi_page'))
            elif user.role == 'Collection':
                return redirect(url_for('collection_desk'))
        else:
            flash('Invalid username or password.', 'danger')
            
    return render_template('login.html')

@app.route('/admin', methods=['GET', 'POST'])
@login_required
def admin_page():
    if current_user.role != 'Admin':
        flash('Unauthorized access.', 'danger')
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'update_settings':
            new_year = request.form.get('active_year')
            new_term = request.form.get('active_term')
            
            year_setting = SystemSetting.query.filter_by(key='active_year').first()
            term_setting = SystemSetting.query.filter_by(key='active_term').first()
            
            if year_setting: year_setting.value = new_year
            else: db.session.add(SystemSetting(key='active_year', value=new_year))
                
            if term_setting: term_setting.value = new_term
            else: db.session.add(SystemSetting(key='active_term', value=new_term))
                
            db.session.commit()
            flash(f'Global system parameters updated successfully to Year {new_year}, Term {new_term}.', 'success')
            return redirect(url_for('admin_page'))

        elif action == 'promote_students':
            context = get_system_context()
            current_active_year = context['active_year']
            try:
                next_year = str(int(current_active_year) + 1)
            except ValueError:
                next_year = "2027"
            
            progression_map = {
                "Grade 10": "Grade 11",
                "Grade 11": "Grade 12",
                "Grade 12": "Graduated",
                "Form 3": "Form 4",
                "Form 4": "Alumni"
            }

            latest_students = Student.query.filter_by(academic_year=current_active_year).all()
            for s in latest_students:
                new_form = progression_map.get(s.form_grade, s.form_grade)
                if new_form in ['Alumni', 'Graduated']:
                    t1, t2, t3, owed = 'N/A', 'N/A', 'N/A', 0
                else:
                    t1, t2, t3, owed = 'Pending', 'Pending', 'Pending', 3
                
                new_student_record = Student(
                    admin_no=s.admin_no, full_name=s.full_name, form_grade=new_form,
                    stream=s.stream, gender=s.gender, academic_year=next_year, term=1,
                    term_1_status=t1, term_2_status=t2, term_3_status=t3, ream_owed=owed
                )
                db.session.add(new_student_record)
            
            year_setting = SystemSetting.query.filter_by(key='active_year').first()
            term_setting = SystemSetting.query.filter_by(key='active_term').first()
            if year_setting: year_setting.value = next_year
            if term_setting: term_setting.value = "1"
            db.session.commit()
            
            flash(f'All students successfully promoted to Academic Year {next_year}!', 'success')
            return redirect(url_for('admin_page'))

        elif action == 'create_user':
            username = request.form.get('username')
            password = request.form.get('password')
            role = request.form.get('role')
            if User.query.filter_by(username=username).first():
                flash('Username already exists!', 'danger')
            else:
                hashed_pw = generate_password_hash(password, method='pbkdf2:sha256')
                db.session.add(User(username=username, password=hashed_pw, role=role))
                db.session.commit()
                flash(f'User {username} created successfully!', 'success')
                
        elif action == 'reset_password':
            user_id = request.form.get('user_id')
            new_password = request.form.get('new_password')
            user_to_reset = User.query.get(int(user_id))
            if user_to_reset:
                user_to_reset.password = generate_password_hash(new_password, method='pbkdf2:sha256')
                db.session.commit()
                flash('Password reset successfully!', 'success')
                
        elif action == 'enroll_student':
            context = get_system_context()
            active_year = context['active_year']
            admin_no = request.form.get('admin_no')
            full_name = request.form.get('full_name')
            form_grade = request.form.get('form_grade')
            stream = request.form.get('stream')
            gender = request.form.get('gender')
            enrollment_term = int(request.form.get('enrollment_term', 1))
            
            if form_grade in ['Alumni', 'Graduated']:
                t1, t2, t3, owed = 'N/A', 'N/A', 'N/A', 0
            else:
                if enrollment_term == 2:
                    t1, t2, t3, owed = 'Exempted', 'Pending', 'Pending', 2
                elif enrollment_term == 3:
                    t1, t2, t3, owed = 'Exempted', 'Exempted', 'Pending', 1
                else:
                    t1, t2, t3, owed = 'Pending', 'Pending', 'Pending', 3
            
            new_student = Student(
                admin_no=admin_no, full_name=full_name, form_grade=form_grade, stream=stream,
                gender=gender, academic_year=active_year, term=enrollment_term,
                term_1_status=t1, term_2_status=t2, term_3_status=t3, ream_owed=owed
            )
            db.session.add(new_student)
            db.session.commit()
            flash(f'Student {full_name} enrolled successfully!', 'success')
                
        elif action == 'delete_student':
            student_id = request.form.get('student_id')
            student = Student.query.get(int(student_id))
            if student:
                db.session.delete(student)
                db.session.commit()
                flash('Student record deleted successfully.', 'success')
                
        elif action == 'bulk_enroll':
            context = get_system_context()
            active_year = context['active_year']
            file = request.files.get('file')
            if not file or file.filename == '':
                flash('No file selected for bulk upload.', 'danger')
            elif not file.filename.endswith('.csv'):
                flash('Please upload a valid .csv file.', 'danger')
            else:
                try:
                    stream_data = file.stream.read().decode("utf-8")
                    stream_io = io.StringIO(stream_data)
                    reader = csv.DictReader(stream_io)
                    
                    count = 0
                    skipped = 0
                    for row in reader:
                        admin_no = row.get('Admin No', '').strip()
                        full_name = row.get('Full Name', '').strip()
                        form_grade = row.get('Form/Grade', '').strip()
                        stream = row.get('Stream', '').strip()
                        gender = row.get('Gender', '').strip()
                        term_str = row.get('Term of Enrollment', '1').strip()
                        
                        if not admin_no or not full_name:
                            skipped += 1
                            continue
                            
                        try:
                            enrollment_term = int(term_str)
                        except ValueError:
                            enrollment_term = 1
                        
                        if form_grade in ['Alumni', 'Graduated']:
                            t1, t2, t3, owed = 'N/A', 'N/A', 'N/A', 0
                        else:
                            if enrollment_term == 2:
                                t1, t2, t3, owed = 'Exempted', 'Pending', 'Pending', 2
                            elif enrollment_term == 3:
                                t1, t2, t3, owed = 'Exempted', 'Exempted', 'Pending', 1
                            else:
                                t1, t2, t3, owed = 'Pending', 'Pending', 'Pending', 3
                        
                        new_student = Student(
                            admin_no=admin_no, full_name=full_name, form_grade=form_grade,
                            stream=stream, gender=gender, academic_year=active_year,
                            term=enrollment_term, term_1_status=t1, term_2_status=t2,
                            term_3_status=t3, ream_owed=owed
                        )
                        db.session.add(new_student)
                        count += 1
                        
                    db.session.commit()
                    flash(f'Successfully bulk enrolled {count} students! ({skipped} rows skipped)', 'success')
                except Exception as e:
                    flash(f'Error processing CSV file: {str(e)}', 'danger')
                
        return redirect(url_for('admin_page'))

    context = get_system_context()
    search_admin_no = request.args.get('admin_no', '').strip()
    filter_year = request.args.get('year', '').strip()
    page = request.args.get('page', 1, type=int)

    query = Student.query
    if search_admin_no:
        query = query.filter(Student.admin_no.ilike(f"%{search_admin_no}%"))
    if filter_year:
        query = query.filter(Student.academic_year == filter_year)

    pagination = query.paginate(page=page, per_page=8, error_out=False)
    students = pagination.items
    users = User.query.all()

    available_years = db.session.query(Student.academic_year).distinct().all()
    available_years = [y[0] for y in available_years if y[0]]

    global_context = {
        'year': context['active_year'],
        'term': context['active_term']
    }

    return render_template('admin.html', 
                           users=users, students=students, pagination=pagination,
                           page=page, total_pages=pagination.pages, 
                           available_years=available_years,
                           global_context=global_context,
                           active_year=context['active_year'],
                           active_term=context['active_term'])
    
@app.route('/hoi')
@login_required
def hoi_page():
    if current_user.role != 'HOI' and current_user.role != 'Admin':
        flash('Unauthorized access.', 'danger')
        return redirect(url_for('login'))
        
    context = get_system_context()
    filter_year = request.args.get('year', context['active_year']).strip()
    filter_term = request.args.get('term', context['active_term']).strip()
    filter_form = request.args.get('form', 'All').strip()
    filter_stream = request.args.get('stream', 'All').strip()
    filter_status = request.args.get('status', 'All').strip()
    
    page = request.args.get('page', 1, type=int)
    per_page = 5
    
    query = Student.query.filter_by(academic_year=filter_year)
    if filter_form != 'All':
        query = query.filter_by(form_grade=filter_form)
    if filter_stream != 'All':
        query = query.filter_by(stream=filter_stream)
        
    students_raw = query.all()
    total_students = len(students_raw)
    total_reams_owed = sum(s.ream_owed for s in students_raw)
    
    total_cleared = 0
    total_pending = 0
    total_exempted = 0
    
    grade_stats = {}
    filtered_students = []
    
    for s in students_raw:
        if s.form_grade not in grade_stats:
            grade_stats[s.form_grade] = {'students': 0, 'cleared': 0, 'pending': 0, 'exempted': 0}
            
        grade_stats[s.form_grade]['students'] += 1
        
        status = s.term_2_status if filter_term == '2' else (s.term_3_status if filter_term == '3' else s.term_1_status)
            
        if status == 'Cleared':
            total_cleared += 1
            grade_stats[s.form_grade]['cleared'] += 1
        elif status == 'Pending':
            total_pending += 1
            grade_stats[s.form_grade]['pending'] += 1
        elif status in ['Exempted', 'N/A']:
            total_exempted += 1
            grade_stats[s.form_grade]['exempted'] += 1
            
        if filter_status == 'Pending' and status != 'Pending':
            continue
        elif filter_status == 'Cleared' and status != 'Cleared':
            continue
        elif filter_status == 'Exempted' and status not in ['Exempted', 'N/A']:
            continue
            
        s.current_term_status = status
        filtered_students.append(s)

    total_filtered_count = len(filtered_students)
    start_idx = (page - 1) * per_page
    paginated_students = filtered_students[start_idx:start_idx + per_page]
    total_pages = (total_filtered_count + per_page - 1) // per_page if total_filtered_count > 0 else 1

    grade_performance = []
    for grade, data in sorted(grade_stats.items()):
        billable = data['cleared'] + data['pending']
        rate = round((data['cleared'] / billable * 100), 1) if billable > 0 else 0
        grade_performance.append({
            'form_grade': grade, 'students': data['students'],
            'cleared': data['cleared'], 'pending': data['pending'],
            'exempted': data['exempted'], 'rate': rate
        })
                
    total_billable = total_cleared + total_pending
    collection_rate = round((total_cleared / total_billable * 100), 1) if total_billable > 0 else 0

    available_years = db.session.query(Student.academic_year).distinct().all()
    available_years = [y[0] for y in available_years if y[0]] or [context['active_year']]
        
    available_grades = [g[0] for g in db.session.query(Student.form_grade).distinct().all() if g[0]]
    available_streams = [st[0] for st in db.session.query(Student.stream).distinct().all() if st[0]]

    return render_template('hoi.html',
                           active_year=context['active_year'], active_term=context['active_term'],
                           filter_year=filter_year, filter_term=filter_term,
                           filter_form=filter_form, filter_stream=filter_stream,
                           filter_status=filter_status, current_page=page,
                           total_pages=total_pages, available_years=available_years,
                           available_grades=available_grades, available_streams=available_streams,
                           total_students=total_students, total_reams_owed=total_reams_owed,
                           total_cleared=total_cleared, total_pending=total_pending,
                           total_exempted=total_exempted, collection_rate=collection_rate,
                           grade_performance=grade_performance, filtered_students=paginated_students)

@app.route('/hoi/compliance-report')
@login_required
def compliance_report():
    if current_user.role not in ['HOI', 'Admin']:
        flash('Unauthorized access.', 'danger')
        return redirect(url_for('login'))
        
    context = get_system_context()
    filter_year = request.args.get('year', context['active_year']).strip()
    filter_term = request.args.get('term', context['active_term']).strip()
    filter_form = request.args.get('form', 'All').strip()
    filter_stream = request.args.get('stream', 'All').strip()
    filter_status = request.args.get('status', 'All').strip()
    
    query = Student.query.filter_by(academic_year=filter_year)
    if filter_form != 'All':
        query = query.filter_by(form_grade=filter_form)
    if filter_stream != 'All':
        query = query.filter_by(stream=filter_stream)
        
    students_raw = query.order_by(Student.form_grade.asc(), Student.admin_no.asc()).all()
    report_rows = []
    
    for s in students_raw:
        status = s.term_2_status if filter_term == '2' else (s.term_3_status if filter_term == '3' else s.term_1_status)
            
        if filter_status == 'Pending' and status != 'Pending': continue
        elif filter_status == 'Cleared' and status != 'Cleared': continue
        elif filter_status == 'Exempted' and status not in ['Exempted', 'N/A']: continue
            
        report_rows.append({
            'admin_no': s.admin_no, 'full_name': s.full_name,
            'form_grade': s.form_grade, 'stream': s.stream,
            'gender': s.gender, 'status': status
        })

    return render_template('compliance_report.html',
                           filter_year=filter_year, filter_term=filter_term,
                           filter_form=filter_form, filter_stream=filter_stream,
                           filter_status=filter_status, report_rows=report_rows,
                           generated_date=datetime.utcnow().strftime('%Y-%m-%d %H:%M'))

@app.route('/hoi/audit-collectors')
@login_required
def audit_collectors():
    if current_user.role not in ['HOI', 'Admin']:
        flash('Unauthorized access.', 'danger')
        return redirect(url_for('login'))
        
    context = get_system_context()
    filter_year = request.args.get('year', context['active_year'])
    filter_term = request.args.get('term', '')
    
    query = CollectionAudit.query.filter_by(academic_year=filter_year)
    if filter_term:
        query = query.filter_by(term=filter_term)
        
    audits = query.order_by(CollectionAudit.timestamp.desc()).all()
    available_years = [y[0] for y in db.session.query(CollectionAudit.academic_year).distinct().all() if y[0]] or [context['active_year']]

    return render_template('audit_collectors.html', audits=audits,
                           available_years=available_years, filter_year=filter_year,
                           filter_term=filter_term, active_year=context['active_year'],
                           active_term=context['active_term'])

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/admin/download-template')
@login_required
def download_template():
    if current_user.role != 'Admin':
        return redirect(url_for('login'))
    
    def generate():
        yield "Admin No,Full Name,Form/Grade,Stream,Gender,Term of Enrollment\n"
        yield "ADM101,Jane Doe,Form 3,Green,Female,1\n"
        yield "ADM102,John Smith,Form 4,Blue,Male,2\n"
    
    return Response(generate(), mimetype='text/csv',
                    headers={"Content-Disposition": "attachment;filename=student_enrollment_template.csv"})

@app.route('/collection', methods=['GET', 'POST'])
@login_required
def collection_desk():
    if current_user.role not in ['Collection', 'Admin']:
        flash('Unauthorized access.', 'danger')
        return redirect(url_for('login'))
        
    context = get_system_context()
    active_year = str(context['active_year'])
    active_term = str(context['active_term']).strip()

    search_query = request.args.get('q', '').strip()
    
    query = Student.query.filter_by(academic_year=active_year)
    if search_query:
        query = query.filter(
            (Student.admin_no.ilike(f"%{search_query}%")) | 
            (Student.full_name.ilike(f"%{search_query}%"))
        )
    students = query.order_by(Student.form_grade.asc(), Student.admin_no.asc()).all()

    if request.method == 'POST':
        student_id = request.form.get('student_id')
        action_type = request.form.get('action_type') # 'clear' or 'revert'
        student_to_update = Student.query.get(int(student_id))
        
        if student_to_update:
            if active_term == '1':
                current_status = student_to_update.term_1_status
            elif active_term == '2':
                current_status = student_to_update.term_2_status
            else:
                current_status = student_to_update.term_3_status

            if action_type == 'clear' and current_status == 'Pending':
                if active_term == '1': student_to_update.term_1_status = 'Cleared'
                elif active_term == '2': student_to_update.term_2_status = 'Cleared'
                elif active_term == '3': student_to_update.term_3_status = 'Cleared'
                
                student_to_update.ream_owed = max(0, student_to_update.ream_owed - 1)
                
                audit = CollectionAudit(
                    collector_username=current_user.username,
                    student_admin_no=student_to_update.admin_no,
                    student_name=student_to_update.full_name,
                    academic_year=active_year,
                    term=active_term,
                    action='Cleared'
                )
                db.session.add(audit)
                db.session.commit()
                flash(f"Successfully cleared ream for {student_to_update.full_name} (Term {active_term})!", "success")
                
            elif action_type == 'revert' and current_status == 'Cleared':
                if active_term == '1': student_to_update.term_1_status = 'Pending'
                elif active_term == '2': student_to_update.term_2_status = 'Pending'
                elif active_term == '3': student_to_update.term_3_status = 'Pending'
                
                student_to_update.ream_owed = student_to_update.ream_owed + 1
                
                audit = CollectionAudit(
                    collector_username=current_user.username,
                    student_admin_no=student_to_update.admin_no,
                    student_name=student_to_update.full_name,
                    academic_year=active_year,
                    term=active_term,
                    action='Reverted'
                )
                db.session.add(audit)
                db.session.commit()
                flash(f"Successfully reverted status for {student_to_update.full_name} (Term {active_term}).", "warning")
                
        return redirect(url_for('collection_desk', q=search_query))

    for s in students:
        if active_term == '1': s.current_status = s.term_1_status
        elif active_term == '2': s.current_status = s.term_2_status
        else: s.current_status = s.term_3_status

    return render_template('collection.html', students=students, search_query=search_query, active_term=active_term)

if __name__ == '__main__':
    app.run(debug=True)