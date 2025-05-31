import sys
import os

# Add the parent directory to Python path so we can import from app.py
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, db, Process, Step, StepVariable

with app.app_context():
    # Find the Kapanış process
    process = Process.query.filter(Process.name.like('%Kapanış%')).first()
    
    if process:
        print(f"Found process: {process.name} (ID: {process.id})")
        
        # Get all steps for this process
        steps = Step.query.filter_by(process_id=process.id).all()
        
        # Update each step to be main_step type
        for step in steps:
            print(f"\nProcessing step: {step.name}")
            print(f"Current type: {step.type}")
            
            # Delete all variables associated with the step
            if step.variables:
                print(f"Deleting {len(step.variables)} variables")
                for var in step.variables:
                    db.session.delete(var)
            
            # Clear file path
            if step.file_path:
                print(f"Clearing file path: {step.file_path}")
                step.file_path = None
            
            # Update type to main_step
            step.type = 'main_step'
            print("Updated to main_step type")
        
        # Commit all changes
        db.session.commit()
        print("\nAll steps updated successfully!")
    else:
        print("No process found with 'Kapanış' in the name") 