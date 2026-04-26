# Shadow Router Disagreement Report

- total: 140
- agreement: 96.43%

## Disagreements

### Turn eval-7d37ea11cd9b-0
- message: `'Ich suche nach Arbeitsblättern für Mathe, könntest du mir da was zeigen?'`
- intent=INT-W-03b state=state-5 persona=P-AND entities={'fach': 'Mathematik', 'medientyp': 'Arbeitsblatt'}
- actual: pattern=PAT-01 intent_final=INT-W-03b state_final=state-5 action=None
- shadow: pattern=PAT-20 intent_override=None state_override=None action=None fired=['rule_vague_search']
- agreement flags: {'intent_match': True, 'state_match': True, 'pattern_match': False, 'action_match': True, 'overall': False}

### Turn eval-224a0cb79ed8-0
- message: `"Gibt's hier Materialien für den Deutschunterricht? Ich bräuchte ein paar Aufgaben für die 5. Klasse."`
- intent=INT-W-03b state=state-5 persona=P-W-LK entities={'fach': 'Deutsch', 'stufe': 'Sekundarstufe I', 'medientyp': 'Aufgaben'}
- actual: pattern=PAT-05 intent_final=INT-W-03b state_final=state-5 action=None
- shadow: pattern=PAT-20 intent_override=None state_override=None action=None fired=['rule_vague_search']
- agreement flags: {'intent_match': True, 'state_match': True, 'pattern_match': False, 'action_match': True, 'overall': False}

### Turn eval-9b8892df50f4-0
- message: `"Ich hab gehört, hier gibt's n paar Materialien. Kann ich die für Deutschunterricht finden?"`
- intent=INT-W-03b state=state-5 persona=P-W-LK entities={'fach': 'Deutsch'}
- actual: pattern=PAT-05 intent_final=INT-W-03b state_final=state-5 action=None
- shadow: pattern=PAT-20 intent_override=None state_override=None action=None fired=['rule_vague_search']
- agreement flags: {'intent_match': True, 'state_match': True, 'pattern_match': False, 'action_match': True, 'overall': False}

### Turn eval-fd639ecf62a7-0
- message: `'Kannst du mir Schritt für Schritt erklären, wie ich mit edu-sharing Materialien finde?'`
- intent=INT-W-03c state=state-8 persona=P-W-SL entities={}
- actual: pattern=PAT-01 intent_final=INT-W-03c state_final=state-8 action=None
- shadow: pattern=PAT-20 intent_override=None state_override=None action=None fired=['rule_vague_search']
- agreement flags: {'intent_match': True, 'state_match': True, 'pattern_match': False, 'action_match': True, 'overall': False}

### Turn eval-64bd0f0b2a14-0
- message: `'Ich benötige Materialien für den Mathematikunterricht, können Sie mir da etwas empfehlen?'`
- intent=INT-W-03b state=state-5 persona=P-W-LK entities={'fach': 'Mathematik'}
- actual: pattern=PAT-01 intent_final=INT-W-03b state_final=state-5 action=None
- shadow: pattern=PAT-20 intent_override=None state_override=None action=None fired=['rule_vague_search']
- agreement flags: {'intent_match': True, 'state_match': True, 'pattern_match': False, 'action_match': True, 'overall': False}