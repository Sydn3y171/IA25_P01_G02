# Dataset: ClassTT_01_tiny.txt (secções #head, #cc, #olw?, #dsd, #tr, #rr, #oc).

import re
from math import ceil
from itertools import combinations
from collections import defaultdict
from constraint import Problem, AllDifferentConstraint

DATASET_PATH = "ClassTT_01_tiny.txt"

# --------------------------
# 1) Parsing do ficheiro
# --------------------------
def load_dataset(path):
    with open(path, "r", encoding="utf-8") as f:
        lines = [ln.rstrip() for ln in f]

    section = None
    head, cc, dsd, tr, rr, oc, olw = [], [], [], [], [], [], []

    for ln in lines:
        # mudar de secção
        if ln.startswith("#head"): section = "head"; continue
        if ln.startswith("#cc"):   section = "cc";   continue
        if ln.startswith("#olw"):  section = "olw";  continue
        if ln.startswith("#dsd"):  section = "dsd";  continue
        if ln.startswith("#tr"):   section = "tr";   continue
        if ln.startswith("#rr"):   section = "rr";   continue
        if ln.startswith("#oc"):   section = "oc";   continue

        # ignorar comentários/linhas vazias
        if ln.startswith("#") or not ln.strip():
            continue

        # guardar linha na secção atual
        if   section == "head": head.append(ln)
        elif section == "cc":   cc.append(ln)
        elif section == "olw":  olw.append(ln)
        elif section == "dsd":  dsd.append(ln)
        elif section == "tr":   tr.append(ln)
        elif section == "rr":   rr.append(ln)
        elif section == "oc":   oc.append(ln)

    return head, cc, dsd, tr, rr, oc, olw

head, cc, dsd, tr, rr, oc, olw = load_dataset(DATASET_PATH)

# --------------------------
# 2) Inferência de parâmetros a partir do #head (sem defaults mágicos)
# --------------------------
# Total de blocos (X..Y)
m_blocks = next((re.search(r"Blocks\s+are\s+numbered\s+from\s+(\d+)\s+to\s+(\d+)", h, re.I)
                 for h in head if "Blocks are numbered" in h), None)
if not m_blocks:
    raise ValueError("Cabeçalho não especifica o intervalo de blocos ('Blocks are numbered from X to Y').")
BL_MIN, BL_MAX = int(m_blocks.group(1)), int(m_blocks.group(2))
BLOCOS = list(range(BL_MIN, BL_MAX + 1))
TOTAL_BLOCOS = len(BLOCOS)

# Blocos por dia (ex.: "Each day has 4 blocks ..." ou "Each day has N blocks")
m_bpd = next((re.search(r"Each\s+day\s+has\s+(\d+)\s+blocks", h, re.I) for h in head
              if "Each day has" in h and "blocks" in h), None)
if not m_bpd:
    raise ValueError("Cabeçalho não especifica 'Each day has N blocks ...'.")
BL_PER_DAY = int(m_bpd.group(1))
if BL_PER_DAY <= 0 or TOTAL_BLOCOS % BL_PER_DAY != 0:
    raise ValueError(f"Inconsistência: TOTAL_BLOCOS={TOTAL_BLOCOS} não é múltiplo de BL_PER_DAY={BL_PER_DAY}.")

NUM_DIAS = TOTAL_BLOCOS // BL_PER_DAY

# Aulas/semana globais (ex.: "all classes have 2 lessons per week")
m_lpw = next((re.search(r"all\s+classes\s+have\s+(\d+)\s+lessons\s+per\s+week", h, re.I) for h in head
              if "lessons per week" in h.lower()), None)
if not m_lpw:
    raise ValueError("Cabeçalho não especifica 'all classes have N lessons per week'.")
LESSONS_PER_WEEK_GLOBAL = int(m_lpw.group(1))
if LESSONS_PER_WEEK_GLOBAL <= 0:
    raise ValueError("Número de aulas/semana inválido no cabeçalho.")

def day_of_block(b):
    """Mapeia bloco → dia (1..NUM_DIAS)."""
    if b < BL_MIN or b > BL_MAX:
        raise ValueError(f"Bloco fora do intervalo: {b}")
    return ((b - BL_MIN) // BL_PER_DAY) + 1

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

# #tr — restrictions (teacher, slots_unavailable*)
teacher_unavail = defaultdict(set)
for row in tr:
    parts = row.split()
    teacher, slots = parts[0], []
    for tok in parts[1:]:
        m = re.match(r"\d+$", tok)
        if m:
            slots.append(int(tok))
    teacher_unavail[teacher].update(slots)

# #rr — room restrictions (course, room)
course_fixed_room = {}
for row in rr:
    parts = row.split()
    if len(parts) >= 2:
        course_fixed_room[parts[0]] = parts[1]

# #oc — online classes (course, lesson_week_index)  | aceita "2" e "2."
course_online_lessons = defaultdict(set)
for row in oc:
    parts = row.split()
    if not parts:
        continue
    course = parts[0]
    m = re.search(r"\d+", row[len(course):])  # primeiro inteiro após o curso
    if not m:
        raise ValueError(f"[Dataset] Linha #oc inválida: {row!r}")
    idx = int(m.group(0))
    course_online_lessons[course].add(idx)

# #olw — overrides de aulas/semana por UC (se existir)
course_lessons_per_week = defaultdict(lambda: LESSONS_PER_WEEK_GLOBAL)
for row in olw:
    parts = row.split()
    if len(parts) >= 2:
        m = re.match(r"^\d+$", parts[1])
        if m:
            course_lessons_per_week[parts[0]] = int(parts[1])

# Conjunto de todas as UCs presentes
all_courses = sorted({c for cs in class_to_courses.values() for c in cs})
# garante entrada para todos na DSD/OLW
for c in all_courses:
    _ = course_lessons_per_week[c]

# --------------------------
# 4) Domínios (derivados do dataset)
# --------------------------
def blocos_para_prof(prof: str):
    """Domínio de blocos sem indisponibilidades do docente (derivado de #tr)."""
    indisps = teacher_unavail.get(prof, set())
    return [b for b in BLOCOS if b not in indisps]

def sala_domain(course: str, lesson_idx: int):
    """
    Domínio da sala, 100% guiado pelo dataset:
      - se lição ∈ #oc → {"Online"}
      - senão, se curso ∈ #rr → {sala fixa}
      - caso contrário → {"SalaLivre"} (placeholder físico neutro)
    """
    if lesson_idx in course_online_lessons.get(course, set()):
        return {"Online"}
    if course in course_fixed_room:
        return {course_fixed_room[course]}
    return {"SalaLivre"}

# --------------------------
# 5) Variáveis no CSP
# --------------------------
problem = Problem()

var_intervalo = {}  # (course, lesson_idx) -> varname
var_sala = {}       # (course, lesson_idx) -> varname

def varname_intervalo(course, k): return f"intervalo_{course}_L{k}"
def varname_sala(course, k):      return f"sala_{course}_L{k}"

# snapshot de domínios (para debug/relato)
dom_snapshot = {}

for course in all_courses:
    prof = course_to_teacher.get(course)
    if not prof:
        raise ValueError(f"[Dataset] Curso '{course}' não tem docente definido em #dsd.")

    blocos_dom = blocos_para_prof(prof)
    if not blocos_dom:
        raise ValueError(f"[Dataset] Docente '{prof}' sem blocos disponíveis (ver #tr / #head).")

    n_lessons = course_lessons_per_week[course]

    for k in range(1, n_lessons + 1):
        v_int = varname_intervalo(course, k)
        v_sala = varname_sala(course, k)

        # valida #oc indices (dataset inconsistente → erro explícito)
        if k in course_online_lessons.get(course, set()) and k > n_lessons:
            raise ValueError(f"[Dataset] Lição {k} de {course} marcada em #oc mas excede o total ({n_lessons}).")

        problem.addVariable(v_int, blocos_dom)
        problem.addVariable(v_sala, sala_domain(course, k))

        var_intervalo[(course, k)] = v_int
        var_sala[(course, k)] = v_sala

        dom_snapshot[v_int] = list(blocos_dom)
        dom_snapshot[v_sala] = list(sala_domain(course, k))

# --------------------------
# 6) Constraints ESSENCIAIS (derivadas do dataset)
# --------------------------
# (a) AllDifferent por turma: nenhuma turma pode ter 2 UCs no mesmo bloco
from collections import defaultdict as dd
turma_to_vars = dd(list)
for turma, courses in class_to_courses.items():
    for c in courses:
        for k in range(1, course_lessons_per_week[c] + 1):
            turma_to_vars[turma].append(var_intervalo[(c, k)])

for turma, vars_int in turma_to_vars.items():
    if len(vars_int) >= 2:
        problem.addConstraint(AllDifferentConstraint(), vars_int)

# (b) AllDifferent por docente: um docente não pode dar 2 aulas no mesmo bloco
prof_to_vars = dd(list)
for c in all_courses:
    prof = course_to_teacher[c]
    for k in range(1, course_lessons_per_week[c] + 1):
        prof_to_vars[prof].append(var_intervalo[(c, k)])

for prof, vars_int in prof_to_vars.items():
    if len(vars_int) >= 2:
        problem.addConstraint(AllDifferentConstraint(), vars_int)

# (c) Conflitos de sala física: mesma sala real + mesmo bloco é proibido
li_keys = [(c, k) for c in all_courses for k in range(1, course_lessons_per_week[c] + 1)]
for (c1, k1), (c2, k2) in combinations(li_keys, 2):
    v1_int, v1_room = var_intervalo[(c1, k1)], var_sala[(c1, k1)]
    v2_int, v2_room = var_intervalo[(c2, k2)], var_sala[(c2, k2)]

    def no_room_clash(b1, r1, b2, r2):
        if b1 != b2:
            return True
        # "Online" e "SalaLivre" não representam salas físicas reais
        if r1 in {"Online", "SalaLivre"} or r2 in {"Online", "SalaLivre"}:
            return True
        return r1 != r2

    problem.addConstraint(no_room_clash, (v1_int, v1_room, v2_int, v2_room))

# Nota: regras como "≤ N aulas/dia por turma" ou "L1/L2 em dias distintos"
# NÃO são impostas aqui para evitar hardcode — só adiciona se vierem codificadas no dataset/enunciado.

# --------------------------
# 7) Resolver e apresentar
# --------------------------
solution = problem.getSolution()
if not solution:
    print(" Não foi encontrada solução com as constraints essenciais.")
else:
    print(f" Solução encontrada. ({len(solution)} variáveis atribuídas)\n")

    # Tabela por turma
    for turma in sorted(class_to_courses.keys()):
        print(f"=== Turma {turma} ===")
        linhas = []
        for c in sorted(class_to_courses[turma]):
            prof = course_to_teacher[c]
            for k in range(1, course_lessons_per_week[c] + 1):
                v_int = var_intervalo[(c, k)]
                v_sala = var_sala[(c, k)]
                bloco = solution[v_int]
                sala  = solution[v_sala]
                dia   = day_of_block(bloco)
                linhas.append((dia, bloco, c, f"L{k}", prof, sala))
        # ordenar por dia → bloco
        linhas.sort()
        print(f"{'Dia':<4} {'Bloco':<6} {'Curso':<6} {'Lição':<6} {'Docente':<10} {'Sala':<12}")
        for dia, bloco, curso, lk, prof, sala in linhas:
            print(f"{dia:<4} {bloco:<6} {curso:<6} {lk:<6} {prof:<10} {sala:<12}")
        print()

    # Vista global por bloco (útil para validar conflitos visuais)
    print("=== Vista global por bloco ===")
    agenda = defaultdict(list)
    for c in all_courses:
        for k in range(1, course_lessons_per_week[c] + 1):
            b = solution[var_intervalo[(c, k)]]
            sala = solution[var_sala[(c, k)]]
            prof = course_to_teacher[c]
            agenda[b].append((c, f"L{k}", prof, sala))

    for b in sorted(agenda.keys()):
        dia = day_of_block(b)
        print(f"Bloco {b:>2} (Dia {dia}):")
        for (c, lk, prof, sala) in sorted(agenda[b]):
            print(f"  - {c} {lk}  | Prof: {prof:<8} | Sala: {sala}")
        print()
