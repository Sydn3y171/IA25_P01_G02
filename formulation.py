from constraint import Problem

# ------------------------------------------------------------
# 1) CONJUNTOS E DOMÍNIOS (adaptar aos vossos dados reais)
# ------------------------------------------------------------

# Dias e slots de 2h (as aulas duram 2h) 
DIAS   = ["Seg", "Ter", "Qua", "Qui", "Sex"]
SLOTS  = [1, 2, 3, 4, 5]   # p.ex., 5 blocos de 2h/dia  (09-11, 11-13, 14-16, 16-18, 18-20)

# Salas (incluir ONLINE se usarem síncronas) 
SALAS  = ["A101", "A102", "Lab1", "Lab2", "ONLINE"]

# Turmas e UCs por turma
TURMAS = ["LEI1A", "LEI1B"]
UCS_POR_TURMA = {
    "LEI1A": ["IP", "MD", "ALGA", "FP"],
    "LEI1B": ["IP", "MD", "ALGA", "FP"],
}

# Nº de aulas semanais por UC (1 ou 2)  [Guia: cada UC pode ter 1–2 aulas/semana]
AULAS_POR_UC = {
    "IP":   2,
    "MD":   1,
    "ALGA": 2,
    "FP":   2,
}

# Docente responsável por UC e disponibilidade (dia, slot)  [Guia: respeitar disponibilidades]
DOCENTE_UC = {"IP": "Prof_IP", "MD": "Prof_MD", "ALGA": "Prof_ALGA", "FP": "Prof_FP"}
DISP_DOCENTE = {
    "Prof_IP":   {("Seg",1), ("Ter",2), ("Qua",3), ("Qui",2), ("Sex",1)},
    "Prof_MD":   {("Seg",2), ("Ter",3), ("Qui",1), ("Sex",2)},
    "Prof_ALGA": {("Ter",1), ("Qua",2), ("Qui",3), ("Sex",3)},
    "Prof_FP":   {("Seg",3), ("Qua",1), ("Qui",2), ("Sex",4)},
}

# UCs online (máx. 3 e no MESMO dia — desafio do guia)
UCS_ONLINE = {"MD"}  # exemplo

# UCs com sala específica (desafio do guia)
SALA_FIXA_UC = {
    # "ALGA": "A101",
    # "FP": "Lab1",
}

# Para controlo de "10 aulas/semana por turma" (Guia: todas as turmas têm 10 aulas/semana)
# Isto deve bater certo com a soma de AULAS_POR_UC para cada turma.
TOTAL_AULAS_TURMA = 10

# ------------------------------------------------------------
# 2) VARIÁVEIS
#   Uma variável por aula de cada UC em cada turma:
#   X[turma, uc, k] ∈ DIAS × SLOTS × SALAS
# ------------------------------------------------------------

def var_name(turma, uc, k):
    return f"X_{turma}_{uc}_{k}"  # k = 1..AULAS_POR_UC[uc]

problem = Problem()

# Domínio base: todos (dia, slot, sala) compatíveis com disponibilidade do docente e sala fixa/online
def dominio_uc(uc):
    docente = DOCENTE_UC[uc]
    pares_dia_slot_ok = DISP_DOCENTE[docente]
    dom = []
    for d, s in pares_dia_slot_ok:
        for sala in SALAS:
            # Se UC é online -> só "ONLINE"
            if uc in UCS_ONLINE and sala != "ONLINE":
                continue
            # Se UC tem sala fixa -> apenas essa
            if uc in SALA_FIXA_UC and sala != SALA_FIXA_UC[uc]:
                continue
            dom.append((d, s, sala))
    return dom

# Criar variáveis
for turma in TURMAS:
    for uc in UCS_POR_TURMA[turma]:
        for k in range(1, AULAS_POR_UC[uc] + 1):
            problem.addVariable(var_name(turma, uc, k), dominio_uc(uc))

# ------------------------------------------------------------
# 3) RESTRIÇÕES DURAS (do guia)
# ------------------------------------------------------------
# (R1) Não sobrepor aulas na mesma SALA: se dois vars têm o mesmo (dia,slot), salas diferentes
def nao_partilham_sala_mesmo_tempo(*vals):
    # vals = [(d,s,sala), ...]
    vistos = set()
    for (d,s,sala) in vals:
        chave = (d, s, sala)
        if chave in vistos:
            return False
        vistos.add(chave)
    return True

# (R2) Uma TURMA não pode ter duas aulas no mesmo (dia,slot)
def turma_sem_sobreposicao(*vals):
    # basta garantir que (dia,slot) não repete entre as variáveis da mesma turma
    vistos = set()
    for (d,s,_) in vals:
        chave = (d, s)
        if chave in vistos:
            return False
        vistos.add(chave)
    return True

# (R3) Máximo 3 aulas por dia por TURMA  [Guia: ≤3/dia]
def max_3_por_dia(*vals):
    cont = {}
    for (d, _, _) in vals:
        cont[d] = cont.get(d, 0) + 1
        if cont[d] > 3:
            return False
    return True

# (R4) Total de 10 aulas/semana por TURMA  [Guia: 10/semana]
def total_10(val_count):
    return val_count == TOTAL_AULAS_TURMA

# Aplicar (R1) a TODAS as variáveis (verificação global de sala/tempo)
todas_vars = []
for turma in TURMAS:
    for uc in UCS_POR_TURMA[turma]:
        for k in range(1, AULAS_POR_UC[uc] + 1):
            todas_vars.append(var_name(turma, uc, k))
problem.addConstraint(nao_partilham_sala_mesmo_tempo, todas_vars)

# Aplicar (R2) e (R3) por TURMA
for turma in TURMAS:
    vars_turma = []
    for uc in UCS_POR_TURMA[turma]:
        for k in range(1, AULAS_POR_UC[uc] + 1):
            vars_turma.append(var_name(turma, uc, k))
    problem.addConstraint(turma_sem_sobreposicao, vars_turma)
    problem.addConstraint(max_3_por_dia, vars_turma)
    # (R4) opcionalmente validar contagem total (nº de variáveis == 10)
    assert len(vars_turma) == TOTAL_AULAS_TURMA, \
        f"Soma de aulas da {turma} deve ser {TOTAL_AULAS_TURMA}"

# (R5) Para UCs online: até 3 aulas e no MESMO dia (desafio do guia)
for turma in TURMAS:
    # junção de todas as aulas online dessa turma
    vars_online = []
    for uc in UCS_POR_TURMA[turma]:
        if uc in UCS_ONLINE:
            for k in range(1, AULAS_POR_UC[uc] + 1):
                vars_online.append(var_name(turma, uc, k))
    if len(vars_online) > 0:
        def online_mesmo_dia(*vals):
            dias = {d for (d, _, _) in vals}
            return len(dias) == 1 and len(vals) <= 3
        problem.addConstraint(online_mesmo_dia, vars_online)

# (R6) Aula da mesma UC na mesma turma não pode partilhar o MESMO dia/slot (garante separação mínima)
for turma in TURMAS:
    for uc in UCS_POR_TURMA[turma]:
        if AULAS_POR_UC[uc] >= 2:
            v1 = var_name(turma, uc, 1)
            v2 = var_name(turma, uc, 2)
            def duas_aulas_slots_distintos(a, b):
                # não podem ser exactamente no mesmo (dia,slot)
                return (a[0], a[1]) != (b[0], b[1])
            problem.addConstraint(duas_aulas_slots_distintos, (v1, v2))

# ------------------------------------------------------------
# 4) SOFT CONSTRAINTS (apenas definidas/descritas nesta fase)
#    (a) Aulas da mesma UC em DIAS distintos
#    (b) Turma com ~4 dias/semana (minimizar nº de dias com aulas)
#    (c) Aulas consecutivas no mesmo dia
#    (d) Minimizar nº de salas distintas usadas por cada turma
#
# ------------------------------------------------------------

if __name__ == "__main__":
    print("Formulação carregada (variáveis, domínios e restrições definidas).")
    
