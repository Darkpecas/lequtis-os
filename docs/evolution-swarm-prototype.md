# Evolution assistant: initial change triage

LeQutis remains the decision authority. The intended assistant helps finish,
stabilise and evolve the existing system, with independent review of its work.
This first component only produces a read-only Git change inventory; it is not
an AI agent, live monitor, semantic drift detector, verifier, or approval gate.

Run against an explicitly chosen trusted baseline commit:

```sh
python3 runtime/evolution_swarm.py --repo . --baseline <commit>
python3 -m unittest discover -s tests -p test_evolution_swarm.py -v
```

It identifies committed, dirty and untracked file changes and tags broad review
areas. A clean result does not prove alignment or safety. Git-ignored files,
database state, the Hostinger host, Hermes, Telegram, semantic meaning, test
outcomes and upstream authenticity are outside its view. No model is called,
no changes are made, and no continuous process is started.

To become the requested assistant, further work needs evidence-linked task
recovery, explicit specialist contracts and budgets, reliable triggers,
independent verification of work and decisions, canonical decision records,
rollback, and a verified live connection to the existing runtime. Avoid treating
this local prototype or the repository's mock swarm evaluation as proof of any
of those capabilities.
