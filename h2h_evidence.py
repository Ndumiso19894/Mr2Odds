"""Optional H2H sample evidence, never a fixture eligibility requirement."""
import h2h_gate

MIN_MEETINGS = h2h_gate.MIN_MEETINGS


def assess(fixture, index):
    """Describe identifiable earlier non-friendly meetings without filtering.

    Counts are lower bounds from available archives, not proof that no other
    meetings took place. Unknown identity or kickoff remains unavailable.
    """
    proof = h2h_gate.eligibility(fixture, index)
    enough = h2h_gate.valid_proof(proof, fixture.get('kickoff'))
    unavailable = proof.get('reason') in ('identity_unavailable', 'kickoff_unavailable')
    return {'status': 'sufficient' if enough else 'unavailable' if unavailable else 'limited',
            'meetings': None if unavailable else proof.get('meetings'),
            'last_meeting': proof.get('last_meeting'), 'identity': proof.get('identity'),
            'minimum_meetings': MIN_MEETINGS}


def preferred(evidence):
    """One tie-break bit, never a probability or selection threshold."""
    if not isinstance(evidence, dict):
        return False
    count = evidence.get('meetings')
    return (evidence.get('status') == 'sufficient' and isinstance(count, int)
            and not isinstance(count, bool) and count >= MIN_MEETINGS)


def row_preferred(row):
    return preferred(getattr(row, 'h2h_evidence', None))
