// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;
// Controlled reference implementation; NOT a GPT-5 API Solidity output.
// Research fixture: no funds, quality certification, or legal adjudication.
contract ReferenceCandidate {
    enum State { Active, Frozen, Challenge, Breach, Restored }
    address public immutable depositor;
    address public immutable analyst;
    address public immutable reviewer;
    bytes32 public immutable approvedCaseId;
    bytes32 public immutable approvedSourceCardHash;
    bytes32 public immutable approvedMachineHash;
    uint16 public constant NOMINAL_LASER_POWER_W = 285;
    uint16 public constant NOMINAL_SCAN_SPEED_MM_S = 960;
    uint16 public constant OXYGEN_UPPER_BOUND_PPM_EXCLUSIVE = 1000;
    uint256 public constant CHALLENGE_WINDOW = 86400;
    State public currentState;
    bool public testReleaseFrozen;
    bool public testDepositFrozen;
    bool public challengeSubmitted;
    uint256 public challengeStart;
    bytes32 public pendingCaseId;
    bytes32 public pendingSourceCardHash;
    bytes32 public pendingEvidenceHash;
    bytes32 public challengeEvidenceHash;
    string public pendingClauseId;
    event RecordSubmitted(bytes32 indexed caseId, bytes32 sourceCardHash,
        bytes32 machineHash, uint16 laserPowerW, uint16 scanSpeedMmS,
        uint16 oxygenPpm, bytes32 evidenceHash, bool metadataMatch);
    event StateTransition(State indexed fromState, State indexed toState,
        string reason, uint256 timestamp);
    event AuditEvidence(bytes32 indexed caseId, bytes32 indexed phaseHash,
        bytes32 indexed clauseHash, string phase, string clauseId,
        bytes32 sourceCardHash, bytes32 evidenceHash, State state,
        uint256 timestamp);
    modifier onlyReviewer() { require(msg.sender == reviewer,"AM: reviewer only"); _; }
    modifier onlyAnalyst() { require(msg.sender == analyst,"AM: analyst only"); _; }
    modifier inChallenge() { require(currentState == State.Challenge,"AM: no challenge open"); _; }
    constructor(address d, address a, address r, bytes32 c, bytes32 s, bytes32 m) {
        require(d != address(0) && a != address(0) && r != address(0),"AM: zero address");
        require(d != a && d != r && a != r,"AM: roles must differ");
        require(c != bytes32(0) && s != bytes32(0) && m != bytes32(0),"AM: zero registry key");
        depositor=d; analyst=a; reviewer=r;
        approvedCaseId=c; approvedSourceCardHash=s; approvedMachineHash=m;
        currentState=State.Active;
    }
    function submitRecord(bytes32 caseId, bytes32 sourceCardHash, bytes32 machineHash,
        uint16 laserPowerW, uint16 scanSpeedMmS, uint16 oxygenPpm, bytes32 evidenceHash)
        external onlyReviewer {
        require(currentState==State.Active || currentState==State.Restored,"AM: record blocked");
        require(evidenceHash != bytes32(0),"AM: empty evidence");
        bool sourceMatch=caseId==approvedCaseId && sourceCardHash==approvedSourceCardHash
            && machineHash==approvedMachineHash;
        bool metadataMatch=laserPowerW==NOMINAL_LASER_POWER_W
            && scanSpeedMmS==NOMINAL_SCAN_SPEED_MM_S
            && oxygenPpm < OXYGEN_UPPER_BOUND_PPM_EXCLUSIVE;
        emit RecordSubmitted(caseId,sourceCardHash,machineHash,laserPowerW,
            scanSpeedMmS,oxygenPpm,evidenceHash,sourceMatch && metadataMatch);
        if (sourceMatch && metadataMatch) {
            _audit(caseId,"record_accepted","Clause_3.2",sourceCardHash,evidenceHash); return;
        }
        pendingCaseId=caseId; pendingSourceCardHash=sourceCardHash;
        pendingEvidenceHash=evidenceHash;
        pendingClauseId=sourceMatch ? "Clause_3.2" : "Clause_3.1";
        challengeEvidenceHash=bytes32(0); challengeSubmitted=false;
        testReleaseFrozen=true; testDepositFrozen=true; challengeStart=block.timestamp;
        _transition(State.Frozen,"provisional test hold");
        _audit(caseId,"freeze",pendingClauseId,sourceCardHash,evidenceHash);
        _transition(State.Challenge,"challenge window opened");
    }
    function submitChallenge(bytes32 evidenceHash) external onlyAnalyst inChallenge {
        require(block.timestamp <= challengeStart+CHALLENGE_WINDOW,"AM: challenge late");
        require(!challengeSubmitted,"AM: challenge already filed");
        require(evidenceHash != bytes32(0),"AM: empty challenge evidence");
        challengeSubmitted=true; challengeEvidenceHash=evidenceHash;
        _audit(pendingCaseId,"challenge_submitted",pendingClauseId,pendingSourceCardHash,evidenceHash);
    }
    function acceptChallenge() external onlyReviewer inChallenge {
        require(challengeSubmitted,"AM: no evidence filed");
        _transition(State.Restored,"challenge accepted");
        testReleaseFrozen=false; testDepositFrozen=false;
        _audit(pendingCaseId,"challenge_accepted",pendingClauseId,pendingSourceCardHash,challengeEvidenceHash);
    }
    function rejectChallenge() external onlyReviewer inChallenge {
        require(challengeSubmitted,"AM: no evidence filed");
        _confirm("challenge rejected",challengeEvidenceHash);
    }
    function finalizeAfterTimeout() external inChallenge {
        require(block.timestamp > challengeStart+CHALLENGE_WINDOW,"AM: window still open");
        require(!challengeSubmitted,"AM: challenge awaiting review");
        _confirm("challenge timeout",pendingEvidenceHash);
    }
    function _confirm(string memory reason, bytes32 evidenceHash) internal {
        _transition(State.Breach,reason);
        _audit(pendingCaseId,"breach_confirmed",pendingClauseId,pendingSourceCardHash,evidenceHash);
    }
    function _transition(State toState, string memory reason) internal {
        State fromState=currentState; currentState=toState;
        emit StateTransition(fromState,toState,reason,block.timestamp);
    }
    function _audit(bytes32 caseId, string memory phase, string memory clauseId,
        bytes32 sourceCardHash, bytes32 evidenceHash) internal {
        emit AuditEvidence(caseId,keccak256(bytes(phase)),keccak256(bytes(clauseId)),
            phase,clauseId,sourceCardHash,evidenceHash,currentState,block.timestamp);
    }
}
