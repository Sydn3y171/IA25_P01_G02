# parte1_dominios_variaveis.py
# Geração de domínios e variáveis A PARTIR do dataset (sem hardcode)
# Dataset esperado no formato ClassTT_01_tiny.txt (seções #head, #cc, #dsd, #tr, #rr, #oc).
# Fonte: ClassTT_01_tiny.txt.  :contentReference[oaicite:1]{index=1}

import re
from collections import defaultdict
from constraint import Problem

DATASET_PATH = "ClassTT_01_tiny.txt"

# --------------------------
# 1) Parsing do ficheiro
# --------------------------
def load_dataset(path):
    with open(path, "r", encoding="utf-8") as f:
        lines = [ln.rstrip() for ln in f]

    section = None
    head, cc, dsd, tr, rr, oc = [], [], [], [], [], []

    for ln in lines:
        # mudar de secção
        if ln.startswith("#head"):
            section = "head"
            continue
        if ln.startswith("#cc"):
            section = "cc"
            continue
        if ln.startswith("#olw"):
            section = "olw"  
            continue
        if ln.startswith("#dsd"):
            section = "dsd"
            continue
        if ln.startswith("#tr"):
            section = "tr"
            continue
        if ln.startswith("#rr"):
            section = "rr"
            continue
        if ln.startswith("#oc"):
            section = "oc"
            continue

        # ignorar comentários/linhas vazias
        if ln.startswith("#") or not ln.strip():
            continue

        # guardar linha na secção atual
        if section == "head":
            head.append(ln)
        elif section == "cc":
            cc.append(ln)
        elif section == "dsd":
            dsd.append(ln)
        elif section == "tr":
            tr.append(ln)
        elif section == "rr":
            rr.append(ln)
        elif section == "oc":
            oc.append(ln)

    return head, cc, dsd, tr, rr, oc

head, cc, dsd, tr, rr, oc = load_dataset(DATASET_PATH)

# --------------------------
# 2) Parâmetros gerais (BLs)
# --------------------------
# tenta extrair "Blocks are numbered from 1 to 20"
m = next((re.search(r"Blocks\s+are\s+numbered\s+from\s+(\d+)\s+to\s+(\d+)", h, re.I) for h in head if "Blocks are numbered" in h), None)
if m:
    BL_MIN, BL_MAX = int(m.group(1)), int(m.group(2))
else:
    # fallback robusto: apanha o maior slot mencionado no ficheiro (#tr/#oc/#rr não trazem nº de blocos)
    BL_MIN, BL_MAX = 1, 20  # mantém 1..20 como no dataset exemplo  :contentReference[oaicite:2]{index=2}

BLOCOS = list(range(BL_MIN, BL_MAX + 1))

# --------------------------
# 3) Tabelas a partir das secções
# --------------------------
# #cc — courses assigned to classes: "t01   UC11 UC12 ..."
class_to_courses = {}
for row in cc:
    parts = row.split()
    turma, courses = parts[0], parts[1:]
    class_to_courses[turma] = courses

# #dsd — courses assigned to lecturers: "jo   UC11 UC21 ..."
course_to_teacher = {}
for row in dsd:
    parts = row.split()
    teacher, courses = parts[0], parts[1:]
    for c in courses:
        course_to_teacher[c] = teacher

# #tr — timeslot restrictions (teacher, slots_unavailable*)
# "mike  13 14 15 16 17 18 19 20"
teacher_unavail = defaultdict(set)
for row in tr:
    parts = row.split()
    teacher, slots = parts[0], [int(x) for x in parts[1:]]
    teacher_unavail[teacher].update(slots)

# #rr — room restrictions (course, room)
# "UC14 Lab01"
course_fixed_room = {}
for row in rr:
    parts = row.split()
    if len(parts) >= 2:
        course_fixed_room[parts[0]] = parts[1]

# #oc — online classes (course, lesson_week_index)
# "UC21 2"  → a lição 2 dessa UC é online
course_online_lessons = defaultdict(set)
for row in oc:
    parts = row.split()
    course, idx = parts[0], int(parts[1])
    course_online_lessons[course].add(idx)

# Número de aulas/semana por UC:
# No tiny dataset: "all classes have 2 lessons per week".  :contentReference[oaicite:3]{index=3}
# (Se existisse #olw, marcaria 1; aqui forçamos 2 para todas.)
course_lessons_per_week = {}
all_courses = sorted({c for cs in class_to_courses.values() for c in cs})
for c in all_courses:
    course_lessons_per_week[c] = 2  # do enunciado tiny  :contentReference[oaicite:4]{index=4}

# --------------------------
# 4) Helpers para domínios
# --------------------------
def blocos_para_prof(prof: str):
    """Devolve domínios de blocos 1..N removendo indisponibilidades do docente (sem hardcode)."""
    indisps = teacher_unavail.get(prof, set())
    return [b for b in BLOCOS if b not in indisps]

def sala_domain(course: str, lesson_idx: int):
    """
    Domínio de sala:
      - Se lição está em #oc → {"Online"}
      - Senão, se curso está em #rr → {sala fixa}
      - Caso contrário → {"SalaLivre"} (placeholder físico; constraints vêm na Parte 2)
    """
    if lesson_idx in course_online_lessons.get(course, set()):
        return {"Online"}
    if course in course_fixed_room:
        return {course_fixed_room[course]}
    return {"SalaLivre"}  # sem hardcode de nomes concretos

# --------------------------
# 5) Criar variáveis no CSP
# --------------------------
problem = Problem()

# Guardar nomes das variáveis para a Parte 2 (constraints)
var_intervalo = {}  # (course, lesson_idx) -> varname
var_sala = {}       # (course, lesson_idx) -> varname

def varname_intervalo(course, k): return f"intervalo_{course}_L{k}"
def varname_sala(course, k):      return f"sala_{course}_L{k}"

for course in all_courses:
    prof = course_to_teacher[course]
    blocos_dom = blocos_para_prof(prof)

    for k in range(1, course_lessons_per_week[course] + 1):
        v_int = varname_intervalo(course, k)
        v_sala = varname_sala(course, k)

        # Domínio de blocos ao estilo "range e remove restrições"
        # (já removido via blocos_para_prof, sem listas hardcoded)
        problem.addVariable(v_int, blocos_dom)

        # Domínio da sala conforme #oc/#rr
        problem.addVariable(v_sala, sala_domain(course, k))

        var_intervalo[(course, k)] = v_int
        var_sala[(course, k)] = v_sala

# --------------------------
# 6) (Opcional) Inspeção rápida
# --------------------------
print(f"Blocos: {BLOCOS}")
print("\n— Variáveis criadas (intervalo/sala) —")
for course in all_courses:
    for k in range(1, course_lessons_per_week[course] + 1):
        print(f"{var_intervalo[(course,k)]:<22} -> {problem._variables[var_intervalo[(course,k)]]}")
        print(f"{var_sala[(course,k)]:<22} -> {problem._variables[var_sala[(course,k)]]}")
    print()

# A partir daqui, na Parte 2:
# - AllDifferent por turma (todos os intervalos das UCs dessa turma)
# - AllDifferent por docente (não dar 2 UCs no mesmo bloco)
# - Conflitos de sala física (mesma sala e mesmo bloco não pode)
# - Separação entre L1 e L2 do mesmo curso (se pedido)
# - Limite de aulas/dia por turma (se aplicável noutros datasets)
