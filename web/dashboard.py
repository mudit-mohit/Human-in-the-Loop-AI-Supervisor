from flask import Flask, render_template, request, jsonify, redirect, url_for
import logging
import sys
import os
from datetime import datetime

# Add parent directory to path so imports work when run from web/ subdirectory
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database.db import Database
from config import Config

logger = logging.getLogger(__name__)

# Configure Flask to look for templates in parent directory's templates folder
app = Flask(__name__, template_folder=os.path.join(os.path.dirname(__file__), '..', 'supervisor', 'templates'))
db = Database()

def simulate_sms_callback(phone_number: str, question: str, answer: str) -> dict:
    """Simulate sending SMS callback to customer"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # Handle None phone_number
    phone_display = phone_number if phone_number else "Unknown"
    question_display = (question or "")[:55]
    answer_display = (answer or "")[:55]
    
    sms_message = f"""
    ╔═══════════════════════════════════════════════════════════╗
    ║                    📱 SMS CALLBACK                         ║
    ╠═══════════════════════════════════════════════════════════╣
    ║ To: {phone_display:<53} ║
    ║ Time: {timestamp:<48} ║
    ╠═══════════════════════════════════════════════════════════╣
    ║ Original Question:                                        ║
    ║ "{question_display}"
    ║                                                            ║
    ║ Supervisor's Answer:                                      ║
    ║ "{answer_display}"
    ╚═══════════════════════════════════════════════════════════╝
    """
    
    logger.info(sms_message)
    print(sms_message)
    
    return {
        'status': 'success',
        'message': f'SMS sent to {phone_display}',
        'phone_number': phone_display,
        'timestamp': timestamp
    }

def has_kb_answer(question: str) -> bool:
    """Let the agent decide — always return False for dashboard (show all escalated questions)"""
    return False
        
@app.route('/')
def dashboard():
    """Main supervisor dashboard"""
    try:
        # Get all pending requests - show ALL pending (agent has already filtered)
        pending_requests = db.get_pending_requests()
        
        # Get stats - count both 'resolved' and 'delivered' as resolved
        all_requests = db.get_all_requests()
        resolved_count = len([r for r in all_requests if r.get('status') in ('resolved', 'delivered')])
        pending_count = len([r for r in all_requests if r.get('status') == 'pending'])
        
        stats = {
            'total_requests': len(all_requests),
            'resolved_requests': resolved_count,
            'pending_requests': pending_count,
            'resolution_rate': (resolved_count / len(all_requests) * 100) if all_requests else 0
        }
        
        logger.info(f"📊 Dashboard stats: Total={len(all_requests)}, Resolved={resolved_count}, Pending={pending_count}, Rate={stats['resolution_rate']:.1f}%")
        
        knowledge_base = db.get_knowledge_base()
        return render_template('dashboard.html', 
                             pending_requests=pending_requests,
                             stats=stats,
                             knowledge_base=knowledge_base,
                             app_name='Glamour Salon Supervisor')
    except Exception as e:
        logger.error(f"Error in dashboard: {e}", exc_info=True)
        return render_template('error.html', error=f'Error loading dashboard: {str(e)}'), 500

@app.route('/request/<request_id>', methods=['GET', 'POST'])
def request_detail(request_id):
    """Display a single help request for answering"""
    try:
        # Handle POST (form submission)
        if request.method == 'POST':
            answer = request.form.get('answer')
            if not answer:
                return render_template('error.html', error='Answer cannot be empty'), 400
            
            # Resolve the request
            db.resolve_request(request_id, answer)
            
            # Get the question and add to knowledge base
            all_reqs = db.get_all_requests()
            req_data = next((r for r in all_reqs if r['id'] == request_id), None)
            if req_data:
                db.add_knowledge(req_data['question'], answer)
                
                # 📱 Send SMS callback to customer
                phone_number = req_data.get('phone_number', 'Unknown')
                question = req_data.get('question', '')
                sms_result = simulate_sms_callback(phone_number, question, answer)
                logger.info(f"📤 SMS Callback: {sms_result}")
            
            logger.info(f"✅ Request {request_id} answered: {answer}")
            
            # Redirect back to dashboard
            return redirect(url_for('dashboard'))
        
        # Handle GET (display form)
        all_requests = db.get_all_requests()
        help_request = next((r for r in all_requests if r['id'] == request_id), None)
        
        if not help_request:
            return render_template('error.html', error='Request not found'), 404
        
        return render_template('request_detail.html',
                             request=help_request,
                             app_name='Glamour Salon Supervisor')
    except Exception as e:
        logger.error(f"Error in request_detail {request_id}: {e}", exc_info=True)
        return render_template('error.html', error=f'Error: {str(e)}'), 500

@app.route('/api/requests', methods=['GET'])
def get_requests():
    """API endpoint to get pending requests that need supervisor attention"""
    try:
        pending = db.get_pending_requests()
        return jsonify([dict(r) for r in pending])
    except Exception as e:
        logger.error(f"Error in get_requests: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@app.route('/api/requests/<request_id>/answer', methods=['POST'])
def answer_request(request_id):
    """API endpoint to answer a request"""
    try:
        data = request.get_json()
        answer = data.get('answer')
        
        if not answer:
            return jsonify({'error': 'Answer is required'}), 400
        
        # Resolve the request
        db.resolve_request(request_id, answer)
        
        # Get the question for this request
        all_reqs = db.get_all_requests()
        req_data = next((r for r in all_reqs if r['id'] == request_id), None)
        if req_data:
            db.add_knowledge(req_data['question'], answer)
            
            # 📱 Send SMS callback to customer
            phone_number = req_data.get('phone_number', 'Unknown')
            sms_result = simulate_sms_callback(phone_number, req_data['question'], answer)
            logger.info(f"📤 SMS Callback: {sms_result}")
        
        logger.info(f"✅ Request {request_id} answered: {answer}")
        return jsonify({'status': 'success', 'sms': sms_result if req_data else None})
        
    except Exception as e:
        logger.error(f"Error answering request: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@app.route('/api/knowledge', methods=['GET'])
def get_knowledge():
    """Get all knowledge base entries"""
    try:
        kb = db.get_knowledge_base()
        return jsonify([{'question': q, 'answer': a} for q, a in kb.items()])
    except Exception as e:
        logger.error(f"Error in get_knowledge: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@app.route('/history')
def history():
    """View history of all requests"""
    try:
        all_requests = db.get_all_requests()
        
        # Debug: Log what we're getting
        logger.info(f"📋 All requests from DB: {len(all_requests)}")
        for req in all_requests:
            logger.info(f"  - ID: {req.get('id')}, Status: {req.get('status')}")
        
        # Separate by status - NO FILTERING, show everything
        resolved = [r for r in all_requests if r.get('status') == 'resolved']
        pending = [r for r in all_requests if r.get('status') == 'pending']
        delivered = [r for r in all_requests if r.get('status') == 'delivered']
        
        # Count resolved + delivered as "resolved"
        total_resolved = len(resolved) + len(delivered)
        
        stats = {
            'total_requests': len(all_requests),
            'resolved_requests': total_resolved,
            'pending_requests': len(pending),
            'resolution_rate': (total_resolved / len(all_requests) * 100) if all_requests else 0
        }
        
        logger.info(f"📊 History stats: Total={len(all_requests)}, Resolved={total_resolved} (resolved={len(resolved)}, delivered={len(delivered)}), Pending={len(pending)}")
        
        # Combine resolved and delivered for display
        all_resolved = resolved + delivered
        
        return render_template('history.html',
                             resolved_requests=all_resolved,
                             pending_requests=pending,
                             stats=stats,
                             app_name='Glamour Salon Supervisor')
    except Exception as e:
        logger.error(f"Error in history route: {e}", exc_info=True)
        return render_template('error.html', error=f'Error: {str(e)}'), 500

@app.route('/api/history')
def get_history():
    """API endpoint to get all requests"""
    try:
        all_requests = db.get_all_requests()
        
        resolved = [dict(r) for r in all_requests if r.get('status') == 'resolved']
        pending = [dict(r) for r in all_requests if r.get('status') == 'pending']
        
        return jsonify({
            'total': len(all_requests),
            'resolved': resolved,
            'pending': pending
        })
    except Exception as e:
        logger.error(f"Error in history API: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@app.route('/debug/kb-check', methods=['POST'])
def debug_kb_check():
    """Debug endpoint to check if a question is in KB"""
    try:
        data = request.get_json()
        question = data.get('question', '')
        
        in_kb = has_kb_answer(question)
        direct_answer = db.get_answer(question.lower())
        
        return jsonify({
            'question': question,
            'in_kb': in_kb,
            'direct_answer': direct_answer,
            'kb_entries': db.get_knowledge_base()
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

def run_web_server():
    """Run the web server"""
    logging.basicConfig(level=logging.INFO)
    logger.info("🌐 Starting supervisor dashboard on http://localhost:5000")
    app.run(host='0.0.0.0', port=5000, debug=False)

if __name__ == '__main__':
    run_web_server()