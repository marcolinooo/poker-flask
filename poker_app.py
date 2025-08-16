# poker_app.py

from flask import Flask, request, jsonify, render_template_string, redirect, url_for, session
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import jwt, datetime, functools

app = Flask(__name__)
app.secret_key = "supersecretkey"
app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql+pymysql://user:password@localhost/pokerdb'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

JWT_SECRET = "jwtsecretkey"

# ---------------- Database ----------------
class Player(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(50))
    cognome = db.Column(db.String(50))
    eta = db.Column(db.Integer)
    capitale = db.Column(db.Float)
    codiceFiscale = db.Column(db.String(50), unique=True)
    role = db.Column(db.String(20), default='PLAYER')
    password = db.Column(db.String(255))

class Event(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(50))
    data = db.Column(db.DateTime)
    numTavoli = db.Column(db.Integer)
    seatsPerTable = db.Column(db.Integer)
    tables = db.relationship('Table', backref='event', lazy=True)
    scores = db.relationship('Score', backref='event', lazy=True)

class Table(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('event.id'))
    seats = db.relationship('Seat', backref='table', lazy=True)

class Seat(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    table_id = db.Column(db.Integer, db.ForeignKey('table.id'))
    player_id = db.Column(db.Integer, db.ForeignKey('player.id'))
    seatNumber = db.Column(db.Integer)
    player = db.relationship('Player')

class Score(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('event.id'))
    player_id = db.Column(db.Integer, db.ForeignKey('player.id'))
    capitaleFinale = db.Column(db.Float, default=0)
    bluffScore = db.Column(db.Float, default=0)
    winScore = db.Column(db.Float, default=0)
    crupierVote = db.Column(db.Float, default=0)

# ---------------- JWT Decorator ----------------
def token_required(f):
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        token = session.get('token')
        if not token:
            return redirect(url_for('login'))
        try:
            data = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
            current_user = Player.query.get(data['id'])
        except:
            return redirect(url_for('login'))
        return f(current_user, *args, **kwargs)
    return decorated

# ---------------- Routes ----------------
@app.route('/')
@token_required
def index(current_user):
    events = Event.query.all()
    return render_template_string(TEMPLATES['index'], user=current_user, events=events)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        data = request.form
        hashed_pw = generate_password_hash(data['password'])
        player = Player(nome=data['nome'], cognome=data['cognome'], eta=data['eta'],
                        capitale=data['capitale'], codiceFiscale=data['codiceFiscale'],
                        password=hashed_pw)
        db.session.add(player)
        db.session.commit()
        return redirect(url_for('login'))
    return render_template_string(TEMPLATES['register'])

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        data = request.form
        user = Player.query.filter_by(codiceFiscale=data['codiceFiscale']).first()
        if user and check_password_hash(user.password, data['password']):
            token = jwt.encode({'id': user.id, 'exp': datetime.datetime.utcnow() + datetime.timedelta(hours=2)},
                               JWT_SECRET, algorithm="HS256")
            session['token'] = token
            return redirect(url_for('index'))
        return "Credenziali errate"
    return render_template_string(TEMPLATES['login'])

@app.route('/create_event', methods=['GET', 'POST'])
@token_required
def create_event(current_user):
    if current_user.role != 'CRUPIER':
        return "Non autorizzato"
    if request.method == 'POST':
        data = request.form
        event = Event(nome=data['nome'], data=datetime.datetime.strptime(data['data'], "%Y-%m-%d"),
                      numTavoli=int(data['numTavoli']), seatsPerTable=int(data['seatsPerTable']))
        db.session.add(event)
        db.session.commit()
        # creare tavoli
        for t in range(event.numTavoli):
            table = Table(event_id=event.id)
            db.session.add(table)
            db.session.commit()
            for s in range(event.seatsPerTable):
                seat = Seat(table_id=table.id, seatNumber=s+1)
                db.session.add(seat)
        db.session.commit()
        return redirect(url_for('index'))
    return render_template_string(TEMPLATES['create_event'])

@app.route('/event/<int:event_id>')
@token_required
def event_detail(current_user, event_id):
    event = Event.query.get_or_404(event_id)
    return render_template_string(TEMPLATES['event_detail'], event=event, user=current_user)

@app.route('/assign_seat/<int:seat_id>', methods=['POST'])
@token_required
def assign_seat(current_user, seat_id):
    seat = Seat.query.get_or_404(seat_id)
    if seat.player_id:
        return "Posto già assegnato"
    player_id = int(request.form['player_id'])
    seat.player_id = player_id
    db.session.commit()
    return redirect(url_for('event_detail', event_id=seat.table.event_id))

@app.route('/add_score/<int:event_id>', methods=['POST'])
@token_required
def add_score(current_user, event_id):
    if current_user.role != 'CRUPIER':
        return "Non autorizzato"
    data = request.form
    score = Score(event_id=event_id, player_id=int(data['player_id']),
                  capitaleFinale=float(data['capitale']),
                  bluffScore=float(data['bluff']),
                  winScore=float(data['win']),
                  crupierVote=float(data['vote']))
    db.session.add(score)
    db.session.commit()
    return redirect(url_for('event_detail', event_id=event_id))

@app.route('/ranking/<int:event_id>')
@token_required
def ranking_event(current_user, event_id):
    event = Event.query.get_or_404(event_id)
    ranking = []
    for s in event.scores:
        total = s.capitaleFinale + s.bluffScore + s.winScore + s.crupierVote
        ranking.append({'player': s.player_id, 'score': total})
    ranking.sort(key=lambda x: x['score'], reverse=True)
    return jsonify(ranking)

# ---------------- Templates ----------------
TEMPLATES = {
    'index': """
    <h2>Benvenuto {{ user.nome }} ({{ user.role }})</h2>
    <a href="{{ url_for('create_event') }}">Crea Evento</a> |
    <a href="{{ url_for('logout') }}">Logout</a>
    <h3>Eventi:</h3>
    <ul>
    {% for e in events %}
      <li><a href="{{ url_for('event_detail', event_id=e.id) }}">{{ e.nome }}</a></li>
    {% endfor %}
    </ul>
    """,
    'register': """
    <form method="post">
    Nome: <input name="nome"><br>
    Cognome: <input name="cognome"><br>
    Età: <input name="eta"><br>
    Capitale: <input name="capitale"><br>
    Codice Fiscale: <input name="codiceFiscale"><br>
    Password: <input name="password" type="password"><br>
    <button type="submit">Registrati</button>
    </form>
    """,
    'login': """
    <form method="post">
    Codice Fiscale: <input name="codiceFiscale"><br>
    Password: <input name="password" type="password"><br>
    <button type="submit">Login</button>
    </form>
    """,
    'create_event': """
    <form method="post">
    Nome Evento: <input name="nome"><br>
    Data (YYYY-MM-DD): <input name="data"><br>
    Numero Tavoli: <input name="numTavoli"><br>
    Posti per Tavolo: <input name="seatsPerTable"><br>
    <button type="submit">Crea Evento</button>
    </form>
    """,
    'event_detail': """
    <h2>Evento: {{ event.nome }}</h2>
    <a href="{{ url_for('index') }}">Torna indietro</a>
    <h3>Tavoli:</h3>
    <ul>
    {% for t in event.tables %}
      <li>Tavolo {{ t.id }}:
        <ul>
        {% for s in t.seats %}
          <li>Posto {{ s.seatNumber }} -
          {% if s.player %}{{ s.player.nome }}{% else %}
          <form method="post" action="{{ url_for('assign_seat', seat_id=s.id) }}">
            <select name="player_id">
              {% for p in Player.query.all() %}
              <option value="{{ p.id }}">{{ p.nome }} {{ p.cognome }}</option>
              {% endfor %}
            </select>
            <button type="submit">Assegna</button>
          </form>
          {% endif %}
          </li>
        {% endfor %}
        </ul>
      </li>
    {% endfor %}
    </ul>
    """
}

@app.route('/logout')
def logout():
    session.pop('token', None)
    return redirect(url_for('login'))

# ---------------- Main ----------------
if __name__ == "__main__":
    db.create_all()
    app.run(host='0.0.0.0', port=5000, debug=True)
