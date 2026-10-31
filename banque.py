# -*- coding: utf-8 -*-
"""
BANQUE / MICROFINANCE - Gestion clientèle, épargne, DAT, crédits,
engagements par signature, comptabilité selon le PCB (UMOA - Burkina Faso).
"""
import os, sys, sqlite3, shutil, calendar, datetime as dt
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
try:
    from PIL import Image, ImageTk
except ImportError:
    Image = None

BASE = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE, 'banque.db')
PHOTOS = os.path.join(BASE, 'photos')
os.makedirs(PHOTOS, exist_ok=True)

# ------------------------------------------------------------------ BASE
SCHEMA = """
CREATE TABLE IF NOT EXISTS clients(id INTEGER PRIMARY KEY, numero TEXT, nom TEXT, type TEXT, naissance TEXT,
  adresse TEXT, tel TEXT, profession TEXT, piece TEXT, photo TEXT, date_ouv TEXT);
CREATE TABLE IF NOT EXISTS signataires(id INTEGER PRIMARY KEY, client_id INT, nom TEXT, qualite TEXT, tel TEXT, piece TEXT, pouvoir TEXT);
CREATE TABLE IF NOT EXISTS comptes(id INTEGER PRIMARY KEY, client_id INT, numero TEXT, type TEXT, solde REAL DEFAULT 0,
  taux REAL DEFAULT 0, date_ouv TEXT, echeance TEXT, duree INT, lien INT, statut TEXT DEFAULT 'OUVERT');
CREATE TABLE IF NOT EXISTS operations(id INTEGER PRIMARY KEY, compte_id INT, date TEXT, libelle TEXT, debit REAL, credit REAL, solde REAL);
CREATE TABLE IF NOT EXISTS credits(id INTEGER PRIMARY KEY, client_id INT, compte_id INT, type TEXT, montant REAL, taux REAL,
  duree INT, date TEXT, statut TEXT DEFAULT 'EN COURS', capital_restant REAL);
CREATE TABLE IF NOT EXISTS echeances(id INTEGER PRIMARY KEY, credit_id INT, n INT, date TEXT, capital REAL, interet REAL, paye INT DEFAULT 0);
CREATE TABLE IF NOT EXISTS engagements(id INTEGER PRIMARY KEY, client_id INT, type TEXT, beneficiaire TEXT, montant REAL,
  commission REAL, date TEXT, echeance TEXT, statut TEXT DEFAULT 'EN COURS');
CREATE TABLE IF NOT EXISTS plan(compte TEXT PRIMARY KEY, libelle TEXT);
CREATE TABLE IF NOT EXISTS ecritures(id INTEGER PRIMARY KEY, date TEXT, piece TEXT, compte TEXT, libelle TEXT, debit REAL, credit REAL);
"""

# Plan comptable bancaire (extrait paramétrable) - À VALIDER avec votre comptable / la Commission Bancaire UMOA.
PLAN = [
    ('101', 'Caisse'), ('111', 'Banque centrale (BCEAO)'),
    ('211', 'Créances commerciales'), ('212', 'Crédits de trésorerie (court terme)'),
    ('213', "Crédits d'équipement (moyen terme)"), ('214', 'Crédits à long terme'),
    ('219', 'Créances en souffrance'),
    ('251', 'Comptes ordinaires créditeurs de la clientèle'), ('252', "Comptes d'épargne"),
    ('253', 'Dépôts à terme de la clientèle'),
    ('661', 'Intérêts sur dépôts de la clientèle'), ('721', 'Intérêts sur crédits à la clientèle'),
    ('731', 'Commissions sur engagements par signature'),
    ('921', 'Engagements de garantie donnés (cautions, avals, crédoc)'),
    ('929', 'Contrepartie des engagements hors bilan'),
]
CPT = {'COURANT': '251', 'EPARGNE': '252', 'DAT': '253'}
CRED = {'COURT TERME': '212', 'MOYEN TERME': '213', 'LONG TERME': '214'}
ENG_TYPES = ['CAUTION', 'AVAL', 'CREDIT DOCUMENTAIRE', 'LETTRE DE GARANTIE', 'AUTRE']

db = sqlite3.connect(DB_PATH)
db.row_factory = sqlite3.Row
db.executescript(SCHEMA)
for c, l in PLAN:
    db.execute("INSERT OR IGNORE INTO plan VALUES(?,?)", (c, l))
db.commit()


class Err(Exception):
    pass


def one(sql, *a): return db.execute(sql, a).fetchone()
def q(sql, *a): return db.execute(sql, a).fetchall()
def ex(sql, *a): return db.execute(sql, a).lastrowid
def today(): return dt.date.today().isoformat()
def fmt(n): return f"{round(n or 0):,}".replace(',', ' ')


def num(s):
    try:
        return float(str(s).replace(' ', '').replace(',', '.'))
    except ValueError:
        raise Err("Montant ou nombre invalide : " + str(s))


def addm(d, n):
    y, m, dd = map(int, d.split('-'))
    m0 = m - 1 + n
    y += m0 // 12
    m = m0 % 12 + 1
    return f"{y:04d}-{m:02d}-{min(dd, calendar.monthrange(y, m)[1]):02d}"


# ------------------------------------------------------------------ MÉTIER
def ecrire(piece, lib, lignes):
    if round(sum(l[1] for l in lignes)) != round(sum(l[2] for l in lignes)):
        raise Err("Écriture comptable déséquilibrée")
    for c, d, cr in lignes:
        if d or cr:
            ex("INSERT INTO ecritures(date,piece,compte,libelle,debit,credit) VALUES(?,?,?,?,?,?)",
               today(), piece, c, lib, d, cr)


def maj_solde(cid, sens, m, lib):
    c = one("SELECT * FROM comptes WHERE id=?", cid)
    if c['statut'] != 'OUVERT':
        raise Err("Compte non ouvert")
    if m <= 0:
        raise Err("Montant invalide")
    if sens == 'DB' and c['solde'] < m:
        raise Err(f"Solde insuffisant ({fmt(c['solde'])} FCFA)")
    s = c['solde'] + (m if sens == 'CR' else -m)
    ex("UPDATE comptes SET solde=? WHERE id=?", s, cid)
    ex("INSERT INTO operations(compte_id,date,libelle,debit,credit,solde) VALUES(?,?,?,?,?,?)",
       cid, today(), lib, m if sens == 'DB' else 0, m if sens == 'CR' else 0, s)


def nouveau_client(d):
    with db:
        n = (one("SELECT COALESCE(MAX(id),0)+1 n FROM clients")['n'])
        return ex("INSERT INTO clients(numero,nom,type,naissance,adresse,tel,profession,piece,date_ouv) VALUES(?,?,?,?,?,?,?,?,?)",
                  f"CLI{n:05d}", d['nom'], d['type'], d['naissance'], d['adresse'], d['tel'], d['profession'], d['piece'], today())


def ouvrir_compte(cli, typ, taux, depot):
    with db:
        c = one("SELECT numero FROM clients WHERE id=?", cli)
        n = one("SELECT COUNT(*) n FROM comptes WHERE client_id=? AND type=?", cli, typ)['n'] + 1
        cid = ex("INSERT INTO comptes(client_id,numero,type,taux,date_ouv) VALUES(?,?,?,?,?)",
                 cli, f"{c['numero']}-{typ[:2]}{n:02d}", typ, taux, today())
        if depot > 0:
            versement(cid, depot, "Dépôt initial")
        return cid


def versement(cid, m, lib="Versement espèces"):
    with db:
        maj_solde(cid, 'CR', m, lib)
        t = CPT[one("SELECT type FROM comptes WHERE id=?", cid)['type']]
        ecrire(f"VRS{cid}", lib, [('101', m, 0), (t, 0, m)])


def retrait(cid, m, lib="Retrait espèces"):
    with db:
        t = one("SELECT type FROM comptes WHERE id=?", cid)['type']
        if t == 'DAT':
            raise Err("Un DAT ne se retire pas : utilisez « Dénouer le DAT »")
        maj_solde(cid, 'DB', m, lib)
        ecrire(f"RET{cid}", lib, [(CPT[t], m, 0), ('101', 0, m)])


def creer_dat(src, m, mois, taux):
    with db:
        s = one("SELECT * FROM comptes WHERE id=?", src)
        if s['type'] == 'DAT':
            raise Err("Choisissez un compte courant ou d'épargne comme source")
        n = one("SELECT COUNT(*) n FROM comptes WHERE client_id=? AND type='DAT'", s['client_id'])['n'] + 1
        cl = one("SELECT numero FROM clients WHERE id=?", s['client_id'])
        maj_solde(src, 'DB', m, "Souscription DAT")
        did = ex("INSERT INTO comptes(client_id,numero,type,taux,date_ouv,echeance,duree,lien) VALUES(?,?,?,?,?,?,?,?)",
                 s['client_id'], f"{cl['numero']}-DA{n:02d}", 'DAT', taux, today(), addm(today(), mois), mois, src)
        maj_solde(did, 'CR', m, "Souscription DAT")
        ecrire(f"DAT{did}", "Souscription DAT", [(CPT[s['type']], m, 0), ('253', 0, m)])


def denouer_dat(did):
    with db:
        d = one("SELECT * FROM comptes WHERE id=? AND type='DAT'", did)
        if not d or d['statut'] != 'OUVERT':
            raise Err("DAT introuvable ou déjà clôturé")
        interet = round(d['solde'] * d['taux'] / 100 * d['duree'] / 12) if today() >= d['echeance'] else 0
        src = one("SELECT * FROM comptes WHERE id=?", d['lien'])
        maj_solde(did, 'DB', d['solde'], "Dénouement DAT")
        maj_solde(src['id'], 'CR', d['solde'] + interet, "Dénouement DAT (capital + intérêts)")
        ex("UPDATE comptes SET statut='CLOTURE' WHERE id=?", did)
        ecrire(f"DNT{did}", "Dénouement DAT", [('253', d['solde'], 0), ('661', interet, 0), (CPT[src['type']], 0, d['solde'] + interet)])
        return interet


def interets_epargne():
    with db:
        tot = 0
        for c in q("SELECT * FROM comptes WHERE type='EPARGNE' AND statut='OUVERT' AND solde>0 AND taux>0"):
            i = round(c['solde'] * c['taux'] / 1200)
            if i > 0:
                maj_solde(c['id'], 'CR', i, "Intérêts d'épargne")
                ecrire(f"INT{c['id']}", "Intérêts d'épargne", [('661', i, 0), ('252', 0, i)])
                tot += i
        return tot


def accorder_credit(cli, cpt, m, taux, mois, typ):
    with db:
        cid = ex("INSERT INTO credits(client_id,compte_id,type,montant,taux,duree,date,capital_restant) VALUES(?,?,?,?,?,?,?,?)",
                 cli, cpt, typ, m, taux, mois, today(), m)
        r = taux / 1200
        mens = m / mois if r == 0 else m * r / (1 - (1 + r) ** -mois)
        cap = m
        for n in range(1, mois + 1):
            i = round(cap * r)
            k = cap if n == mois else round(mens) - i
            ex("INSERT INTO echeances(credit_id,n,date,capital,interet) VALUES(?,?,?,?,?)", cid, n, addm(today(), n), k, i)
            cap -= k
        maj_solde(cpt, 'CR', m, f"Déblocage crédit n°{cid}")
        ecrire(f"CRD{cid}", f"Déblocage crédit n°{cid}", [(CRED[typ], m, 0), ('251', 0, m)])
        return cid


def rembourser(crid):
    with db:
        cr = one("SELECT * FROM credits WHERE id=?", crid)
        e = one("SELECT * FROM echeances WHERE credit_id=? AND paye=0 ORDER BY n LIMIT 1", crid)
        if not e:
            raise Err("Crédit déjà soldé")
        tot = e['capital'] + e['interet']
        maj_solde(cr['compte_id'], 'DB', tot, f"Échéance {e['n']} crédit n°{crid}")
        ecrire(f"RMB{crid}-{e['n']}", f"Échéance {e['n']} crédit n°{crid}",
               [('251', tot, 0), (CRED[cr['type']], 0, e['capital']), ('721', 0, e['interet'])])
        ex("UPDATE echeances SET paye=1 WHERE id=?", e['id'])
        ex("UPDATE credits SET capital_restant=capital_restant-? WHERE id=?", e['capital'], crid)
        if not one("SELECT 1 FROM echeances WHERE credit_id=? AND paye=0", crid):
            ex("UPDATE credits SET statut='SOLDE' WHERE id=?", crid)


def nouvel_engagement(cli, typ, benef, m, comm_pct, mois, cpt):
    with db:
        com = round(m * comm_pct / 100)
        eid = ex("INSERT INTO engagements(client_id,type,beneficiaire,montant,commission,date,echeance) VALUES(?,?,?,?,?,?,?)",
                 cli, typ, benef, m, com, today(), addm(today(), mois))
        ecrire(f"ENG{eid}", f"{typ} en faveur de {benef}", [('921', m, 0), ('929', 0, m)])
        if com > 0:
            maj_solde(cpt, 'DB', com, f"Commission {typ} n°{eid}")
            ecrire(f"COM{eid}", f"Commission {typ} n°{eid}", [('251', com, 0), ('731', 0, com)])


def mainlevee(eid):
    with db:
        e = one("SELECT * FROM engagements WHERE id=?", eid)
        if e['statut'] != 'EN COURS':
            raise Err("Engagement déjà levé")
        ex("UPDATE engagements SET statut='LEVE' WHERE id=?", eid)
        ecrire(f"MLV{eid}", f"Mainlevée {e['type']} n°{eid}", [('929', e['montant'], 0), ('921', 0, e['montant'])])


# ------------------------------------------------------------------ UI utilitaires
def safe(f):
    def w(*a, **k):
        try:
            return f(*a, **k)
        except Err as e:
            messagebox.showwarning("Attention", str(e))
        except Exception as e:
            messagebox.showerror("Erreur", repr(e))
    return w


def F(k, l, df='', ch=None): return (k, l, df, ch)


def form(parent, title, fields):
    d = tk.Toplevel(parent); d.title(title); d.transient(parent); d.grab_set()
    ent = {}
    for i, (k, l, df, ch) in enumerate(fields):
        ttk.Label(d, text=l).grid(row=i, column=0, sticky='w', padx=8, pady=3)
        if ch:
            w = ttk.Combobox(d, values=ch, state='readonly', width=30); w.set(df or ch[0])
        else:
            w = ttk.Entry(d, width=33); w.insert(0, df)
        w.grid(row=i, column=1, padx=8, pady=3); ent[k] = w
    out = [None]

    def ok():
        out[0] = {k: w.get().strip() for k, w in ent.items()}; d.destroy()
    ttk.Button(d, text='Valider', command=ok).grid(row=len(fields), column=0, columnspan=2, pady=8)
    parent.wait_window(d)
    return out[0]


def tree(p, cols, w=None):
    f = ttk.Frame(p)
    t = ttk.Treeview(f, columns=cols, show='headings', height=10)
    for i, c in enumerate(cols):
        t.heading(c, text=c); t.column(c, width=(w[i] if w else 110), anchor='w')
    sb = ttk.Scrollbar(f, command=t.yview); t.configure(yscrollcommand=sb.set)
    t.pack(side='left', fill='both', expand=True); sb.pack(side='right', fill='y')
    f.pack(fill='both', expand=True, padx=4, pady=4)
    return t


def fill(t, rows):
    t.delete(*t.get_children())
    for iid, v in rows:
        t.insert('', 'end', iid=str(iid), values=v)


def sel(t):
    s = t.selection()
    if not s:
        raise Err("Sélectionnez d'abord une ligne")
    return int(s[0])


def buttons(p, items):
    f = ttk.Frame(p); f.pack(fill='x', padx=4, pady=2)
    for txt, cmd in items:
        ttk.Button(f, text=txt, command=safe(cmd)).pack(side='left', padx=2)


def show_table(parent, title, cols, rows):
    w = tk.Toplevel(parent); w.title(title); w.geometry('760x420')
    t = tree(w, cols, [140] * len(cols))
    fill(t, list(enumerate(rows)))


# ------------------------------------------------------------------ DOSSIER CLIENT
class Dossier(tk.Toplevel):
    def __init__(s, app, cid):
        super().__init__(app.root)
        s.app, s.cid = app, cid
        s.geometry('1080x640')
        left = ttk.Frame(s); left.pack(side='left', fill='y', padx=10, pady=10)
        s.lphoto = ttk.Label(left, text='Pas de photo', relief='groove', anchor='center', width=26)
        s.lphoto.pack(ipady=70)
        ttk.Button(left, text='Choisir / changer la photo', command=safe(s.chg_photo)).pack(pady=4)
        s.info = ttk.Label(left, justify='left', wraplength=230); s.info.pack(anchor='w', pady=8)
        nb = ttk.Notebook(s); nb.pack(side='left', fill='both', expand=True, padx=6, pady=8)
        s.tsyn = tk.Text(nb, font=('Consolas', 11), state='disabled'); nb.add(s.tsyn, text='Situation globale')
        # Signataires
        f = ttk.Frame(nb); nb.add(f, text='Signataires')
        buttons(f, [('Ajouter', s.add_sig), ('Supprimer', s.del_sig)])
        s.tsig = tree(f, ('Nom', 'Qualité', 'Téléphone', 'Pièce', 'Pouvoir / limite'), [180, 110, 100, 110, 160])
        # Comptes
        f = ttk.Frame(nb); nb.add(f, text='Comptes & épargne')
        buttons(f, [('Ouvrir un compte', s.add_cpt), ('Versement', s.vers), ('Retrait', s.ret), ('Relevé', s.releve)])
        s.tcpt = tree(f, ('N° compte', 'Type', 'Solde (FCFA)', 'Taux %', 'Ouvert le', 'Statut'), [140, 90, 120, 70, 100, 80])
        # DAT
        f = ttk.Frame(nb); nb.add(f, text='DAT')
        buttons(f, [('Nouveau DAT', s.add_dat), ('Dénouer le DAT', s.den_dat)])
        s.tdat = tree(f, ('N° DAT', 'Montant', 'Taux %', 'Durée (mois)', 'Échéance', 'Statut'), [140, 110, 70, 90, 100, 80])
        # Crédits
        f = ttk.Frame(nb); nb.add(f, text='Crédits')
        buttons(f, [('Nouveau crédit', s.add_cred), ('Rembourser échéance', s.remb), ('Échéancier', s.ech)])
        s.tcre = tree(f, ('N°', 'Type', 'Montant', 'Taux %', 'Durée', 'Date', 'Reste dû (capital)', 'Statut'), [40, 100, 100, 60, 60, 90, 120, 80])
        # Engagements
        f = ttk.Frame(nb); nb.add(f, text='Cautions & engagements')
        buttons(f, [('Nouvel engagement', s.add_eng), ('Mainlevée', s.lever)])
        s.teng = tree(f, ('N°', 'Type', 'Bénéficiaire', 'Montant', 'Commission', 'Échéance', 'Statut'), [40, 140, 160, 100, 90, 100, 80])
        s.refresh()

    def refresh(s):
        c = one("SELECT * FROM clients WHERE id=?", s.cid)
        s.title(f"Dossier {c['numero']} - {c['nom']}")
        s.info.config(text=f"{c['numero']}\n{c['nom']}\n{c['type']}\nNé(e) le : {c['naissance']}\nProfession : {c['profession']}\n"
                           f"Tél : {c['tel']}\nAdresse : {c['adresse']}\nPièce : {c['piece']}\nOuvert le : {c['date_ouv']}")
        if c['photo'] and os.path.exists(c['photo']) and Image:
            im = Image.open(c['photo']); im.thumbnail((210, 260))
            s._img = ImageTk.PhotoImage(im); s.lphoto.config(image=s._img, text='')
        fill(s.tsig, [(r['id'], (r['nom'], r['qualite'], r['tel'], r['piece'], r['pouvoir'])) for r in q("SELECT * FROM signataires WHERE client_id=?", s.cid)])
        fill(s.tcpt, [(r['id'], (r['numero'], r['type'], fmt(r['solde']), r['taux'], r['date_ouv'], r['statut']))
                      for r in q("SELECT * FROM comptes WHERE client_id=? AND type<>'DAT'", s.cid)])
        fill(s.tdat, [(r['id'], (r['numero'], fmt(r['solde']), r['taux'], r['duree'], r['echeance'], r['statut']))
                      for r in q("SELECT * FROM comptes WHERE client_id=? AND type='DAT'", s.cid)])
        fill(s.tcre, [(r['id'], (r['id'], r['type'], fmt(r['montant']), r['taux'], r['duree'], r['date'], fmt(r['capital_restant']), r['statut']))
                      for r in q("SELECT * FROM credits WHERE client_id=?", s.cid)])
        fill(s.teng, [(r['id'], (r['id'], r['type'], r['beneficiaire'], fmt(r['montant']), fmt(r['commission']), r['echeance'], r['statut']))
                      for r in q("SELECT * FROM engagements WHERE client_id=?", s.cid)])
        sm = lambda t: one("SELECT COALESCE(SUM(solde),0) v FROM comptes WHERE client_id=? AND type=? AND statut='OUVERT'", s.cid, t)['v']
        cre = one("SELECT COALESCE(SUM(capital_restant),0) v, COUNT(*) n FROM credits WHERE client_id=? AND statut='EN COURS'", s.cid)
        eng = one("SELECT COALESCE(SUM(montant),0) v, COUNT(*) n FROM engagements WHERE client_id=? AND statut='EN COURS'", s.cid)
        txt = (f"SITUATION GLOBALE AU {today()}\n{'=' * 54}\n"
               f"Comptes courants ......... {fmt(sm('COURANT')):>15} FCFA\n"
               f"Épargne .................. {fmt(sm('EPARGNE')):>15} FCFA\n"
               f"Dépôts à terme (DAT) ..... {fmt(sm('DAT')):>15} FCFA\n"
               f"{'-' * 54}\n"
               f"Crédits en cours ({cre['n']}) ...... {fmt(cre['v']):>15} FCFA (capital restant)\n"
               f"Engagements par signature ({eng['n']}) {fmt(eng['v']):>12} FCFA\n"
               f"{'-' * 54}\n"
               f"Signataires : {len(q('SELECT 1 FROM signataires WHERE client_id=?', s.cid))}\n")
        s.tsyn.config(state='normal'); s.tsyn.delete('1.0', 'end'); s.tsyn.insert('1.0', txt); s.tsyn.config(state='disabled')
        s.app.refresh()

    def chg_photo(s):
        p = filedialog.askopenfilename(filetypes=[('Images', '*.png *.jpg *.jpeg *.gif *.bmp')])
        if p:
            dest = os.path.join(PHOTOS, f"{s.cid}{os.path.splitext(p)[1]}")
            shutil.copy(p, dest)
            ex("UPDATE clients SET photo=? WHERE id=?", dest, s.cid); db.commit()
            s.refresh()

    def add_sig(s):
        d = form(s, 'Nouveau signataire', [F('nom', 'Nom et prénoms'), F('qualite', 'Qualité', 'Mandataire', ['Titulaire', 'Mandataire', 'Gérant', 'Directeur', 'Autre']),
                                           F('tel', 'Téléphone'), F('piece', 'N° pièce (CNIB...)'), F('pouvoir', 'Pouvoir / limite', 'Illimité')])
        if d and d['nom']:
            ex("INSERT INTO signataires(client_id,nom,qualite,tel,piece,pouvoir) VALUES(?,?,?,?,?,?)", s.cid, d['nom'], d['qualite'], d['tel'], d['piece'], d['pouvoir'])
            db.commit(); s.refresh()

    def del_sig(s):
        ex("DELETE FROM signataires WHERE id=?", sel(s.tsig)); db.commit(); s.refresh()

    def add_cpt(s):
        d = form(s, 'Ouverture de compte', [F('t', 'Type', ch=['COURANT', 'EPARGNE']), F('taux', 'Taux annuel % (épargne)', '0'), F('dep', 'Dépôt initial (FCFA)', '0')])
        if d:
            ouvrir_compte(s.cid, d['t'], num(d['taux']), num(d['dep'])); s.refresh()

    def vers(s):
        i = sel(s.tcpt); d = form(s, 'Versement', [F('m', 'Montant (FCFA)')])
        if d: versement(i, num(d['m'])); s.refresh()

    def ret(s):
        i = sel(s.tcpt); d = form(s, 'Retrait', [F('m', 'Montant (FCFA)')])
        if d: retrait(i, num(d['m'])); s.refresh()

    def releve(s):
        i = sel(s.tcpt) if s.tcpt.selection() else sel(s.tdat)
        show_table(s, 'Relevé de compte', ('Date', 'Libellé', 'Débit', 'Crédit', 'Solde'),
                   [(r['date'], r['libelle'], fmt(r['debit']), fmt(r['credit']), fmt(r['solde'])) for r in q("SELECT * FROM operations WHERE compte_id=? ORDER BY id", i)])

    def add_dat(s):
        cs = [f"{r['id']} - {r['numero']} ({fmt(r['solde'])})" for r in q("SELECT * FROM comptes WHERE client_id=? AND type<>'DAT' AND statut='OUVERT'", s.cid)]
        if not cs: raise Err("Ouvrez d'abord un compte courant ou d'épargne")
        d = form(s, 'Nouveau DAT', [F('src', 'Compte débité', ch=cs), F('m', 'Montant (FCFA)'), F('mois', 'Durée (mois)', '12'), F('taux', 'Taux annuel %', '5')])
        if d: creer_dat(int(d['src'].split(' - ')[0]), num(d['m']), int(num(d['mois'])), num(d['taux'])); s.refresh()

    def den_dat(s):
        i = sel(s.tdat)
        if messagebox.askyesno('Dénouer', 'Dénouer ce DAT ? (sans intérêts si avant échéance)'):
            messagebox.showinfo('DAT', f"DAT dénoué. Intérêts versés : {fmt(denouer_dat(i))} FCFA"); s.refresh()

    def add_cred(s):
        cs = [f"{r['id']} - {r['numero']}" for r in q("SELECT * FROM comptes WHERE client_id=? AND type='COURANT' AND statut='OUVERT'", s.cid)]
        if not cs: raise Err("Le client doit avoir un compte courant pour le déblocage")
        d = form(s, 'Nouveau crédit', [F('cpt', 'Compte à créditer', ch=cs), F('typ', 'Type', ch=list(CRED)), F('m', 'Montant (FCFA)'), F('taux', 'Taux annuel %', '12'), F('mois', 'Durée (mois)', '12')])
        if d: accorder_credit(s.cid, int(d['cpt'].split(' - ')[0]), num(d['m']), num(d['taux']), int(num(d['mois'])), d['typ']); s.refresh()

    def remb(s):
        rembourser(sel(s.tcre)); s.refresh()

    def ech(s):
        i = sel(s.tcre)
        show_table(s, f'Échéancier crédit n°{i}', ('N°', 'Date', 'Capital', 'Intérêts', 'Total', 'Payé'),
                   [(r['n'], r['date'], fmt(r['capital']), fmt(r['interet']), fmt(r['capital'] + r['interet']), 'OUI' if r['paye'] else '') for r in q("SELECT * FROM echeances WHERE credit_id=? ORDER BY n", i)])

    def add_eng(s):
        cs = [f"{r['id']} - {r['numero']}" for r in q("SELECT * FROM comptes WHERE client_id=? AND type='COURANT' AND statut='OUVERT'", s.cid)]
        if not cs: raise Err("Le client doit avoir un compte courant (prélèvement de la commission)")
        d = form(s, 'Engagement par signature', [F('typ', 'Type', ch=ENG_TYPES), F('b', 'Bénéficiaire'), F('m', 'Montant (FCFA)'), F('c', 'Commission %', '1'), F('mois', 'Durée (mois)', '12'), F('cpt', 'Compte débité (commission)', ch=cs)])
        if d: nouvel_engagement(s.cid, d['typ'], d['b'], num(d['m']), num(d['c']), int(num(d['mois'])), int(d['cpt'].split(' - ')[0])); s.refresh()

    def lever(s):
        mainlevee(sel(s.teng)); s.refresh()


# ------------------------------------------------------------------ APPLICATION
class App:
    def __init__(s):
        s.root = tk.Tk(); s.root.title('BANQUE - Gestion épargne, crédits et engagements (PCB UMOA)'); s.root.geometry('1100x640')
        nb = ttk.Notebook(s.root); nb.pack(fill='both', expand=True)
        # Clients
        f = ttk.Frame(nb); nb.add(f, text='Clients')
        bar = ttk.Frame(f); bar.pack(fill='x', padx=4, pady=4)
        ttk.Button(bar, text='Nouveau client', command=safe(s.new_client)).pack(side='left', padx=2)
        ttk.Button(bar, text='Ouvrir le dossier', command=safe(s.open_dossier)).pack(side='left', padx=2)
        ttk.Label(bar, text='  Recherche :').pack(side='left')
        s.search = tk.StringVar(); e = ttk.Entry(bar, textvariable=s.search, width=30); e.pack(side='left')
        s.search.trace_add('write', lambda *a: s.refresh())
        s.tcli = tree(f, ('N° client', 'Nom', 'Type', 'Téléphone', 'Épargne+Courant', 'DAT', 'Crédits (reste dû)', 'Engagements'), [90, 220, 100, 110, 120, 110, 130, 110])
        s.tcli.bind('<Double-1>', lambda e: safe(s.open_dossier)())
        # Crédits
        f = ttk.Frame(nb); nb.add(f, text='Portefeuille crédits')
        s.tcre = tree(f, ('N°', 'Client', 'Type', 'Montant', 'Taux %', 'Durée', 'Reste dû', 'Statut'), [40, 220, 110, 110, 60, 60, 110, 80])
        # Engagements
        f = ttk.Frame(nb); nb.add(f, text='Engagements par signature')
        s.teng = tree(f, ('N°', 'Client', 'Type', 'Bénéficiaire', 'Montant', 'Échéance', 'Statut'), [40, 200, 140, 180, 110, 100, 80])
        # Comptabilité
        f = ttk.Frame(nb); nb.add(f, text='Comptabilité PCB')
        buttons(f, [('Calculer intérêts épargne du mois', s.int_ep)])
        sub = ttk.Notebook(f); sub.pack(fill='both', expand=True)
        g = ttk.Frame(sub); sub.add(g, text='Balance'); s.tbal = tree(g, ('Compte', 'Libellé', 'Débit', 'Crédit', 'Solde'), [80, 330, 130, 130, 130])
        g = ttk.Frame(sub); sub.add(g, text='Journal'); s.tjou = tree(g, ('Date', 'Pièce', 'Compte', 'Libellé', 'Débit', 'Crédit'), [90, 90, 70, 330, 110, 110])
        g = ttk.Frame(sub); sub.add(g, text='Plan comptable'); s.tpla = tree(g, ('Compte', 'Libellé'), [90, 500])
        s.refresh()

    def refresh(s):
        k = s.search.get().lower()
        rows = []
        for c in q("SELECT * FROM clients ORDER BY id DESC"):
            if k and k not in (c['nom'] + c['numero']).lower(): continue
            sm = lambda t: one("SELECT COALESCE(SUM(solde),0) v FROM comptes WHERE client_id=? AND type IN (%s) AND statut='OUVERT'" % t, c['id'])['v']
            cr = one("SELECT COALESCE(SUM(capital_restant),0) v FROM credits WHERE client_id=? AND statut='EN COURS'", c['id'])['v']
            en = one("SELECT COALESCE(SUM(montant),0) v FROM engagements WHERE client_id=? AND statut='EN COURS'", c['id'])['v']
            rows.append((c['id'], (c['numero'], c['nom'], c['type'], c['tel'], fmt(sm("'COURANT','EPARGNE'")), fmt(sm("'DAT'")), fmt(cr), fmt(en))))
        fill(s.tcli, rows)
        fill(s.tcre, [(r['id'], (r['id'], r['nom'], r['type'], fmt(r['montant']), r['taux'], r['duree'], fmt(r['capital_restant']), r['statut']))
                      for r in q("SELECT cr.*, c.nom FROM credits cr JOIN clients c ON c.id=cr.client_id ORDER BY cr.id DESC")])
        fill(s.teng, [(r['id'], (r['id'], r['nom'], r['type'], r['beneficiaire'], fmt(r['montant']), r['echeance'], r['statut']))
                      for r in q("SELECT e.*, c.nom FROM engagements e JOIN clients c ON c.id=e.client_id ORDER BY e.id DESC")])
        bal = q("SELECT p.compte, p.libelle, COALESCE(SUM(e.debit),0) d, COALESCE(SUM(e.credit),0) c FROM plan p LEFT JOIN ecritures e ON e.compte=p.compte GROUP BY p.compte ORDER BY p.compte")
        fill(s.tbal, [(r['compte'], (r['compte'], r['libelle'], fmt(r['d']), fmt(r['c']), fmt(r['d'] - r['c']))) for r in bal])
        fill(s.tjou, [(r['id'], (r['date'], r['piece'], r['compte'], r['libelle'], fmt(r['debit']), fmt(r['credit']))) for r in q("SELECT * FROM ecritures ORDER BY id DESC LIMIT 500")])
        fill(s.tpla, [(r['compte'], (r['compte'], r['libelle'])) for r in q("SELECT * FROM plan ORDER BY compte")])

    def new_client(s):
        d = form(s.root, 'Nouveau client', [F('nom', 'Nom et prénoms / Raison sociale'), F('type', 'Type', ch=['Particulier', 'Entreprise', 'Association', 'Groupement']),
                                            F('naissance', 'Date de naissance / création'), F('profession', 'Profession / Activité'), F('tel', 'Téléphone'),
                                            F('adresse', 'Adresse'), F('piece', 'N° pièce d\'identité (CNIB...)')])
        if d and d['nom']:
            cid = nouveau_client(d); s.refresh(); Dossier(s, cid)

    def open_dossier(s):
        Dossier(s, sel(s.tcli))

    def int_ep(s):
        messagebox.showinfo('Intérêts', f"Intérêts d'épargne crédités : {fmt(interets_epargne())} FCFA"); s.refresh()


if __name__ == '__main__':
    App().root.mainloop()
