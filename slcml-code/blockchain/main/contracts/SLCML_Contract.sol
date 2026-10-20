// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import { SD59x18, sd, convert, UNIT } from "@prb/math/src/SD59x18.sol";

/**
 * @title  SLCML_Contract v2.0
 * @notice Judicially auditable smart legal contract based on SLCML quintuple model <S, O, C, R, A>
 * @dev    Implements Algorithm 1 (Dynamic Segmented Privacy Budget Control)
 *         and Algorithm 2 (Oracle-Driven Procedural Accountability)
 *         with Freeze -> Challenge -> Adjudication three-phase procedural justice control flow.
 */
contract SLCML_Contract {

    struct Subject {
        address addr;
        bytes32 credentialHash;
        uint256 reputation;
        uint256 callCount;
        bool    isRegistered;
    }

    struct DataAsset {
        bytes32 assetId;
        uint8   sensitivityLevel;
        uint256 bTotal;
        uint256 bRem;
        string  dataRegion;
    }

    struct JudicialEvidence {
        uint256 blockTimestamp;
        uint256 blockNumber;
        address violatingParty;
        string  violationType;
        string  clauseId;
        bytes32 evidenceHash;
        string  nlFactStatement;
        bytes32 oracleDataHash;
        uint256 penaltyAmount;
    }

    struct AppealRecord {
        bytes32 evidenceHash;
        uint256 submitTime;
        bool    isRejected;
    }

    mapping(address => Subject) public subjects;
    Subject public dataOwnerSubject;
    Subject public modelProviderSubject;

    DataAsset public dataAsset;

    uint256 public depositBalance;

    enum ContractState { Active, RiskWarning, Challenge, Breach, Resolved }
    ContractState public currentState;

    uint256 public challengeStartTime;
    uint256 public constant CHALLENGE_WINDOW = 72 hours;

    string  private pendingViolationType;
    string  private pendingClauseId;
    bytes32 private pendingOracleHash;

    JudicialEvidence[] public evidenceLog;

    AppealRecord public currentAppeal;
    bool public appealSubmitted;

    uint256 public constant REPUTATION_INITIAL      = 100;
    uint256 public constant REPUTATION_PENALTY_STEP = 5;
    uint256 public constant ALPHA_NUMERATOR         = 1;
    uint256 public constant ALPHA_DENOMINATOR       = 10;
    uint256 public constant BUDGET_CRITICAL_PCT    = 10;
    uint256 public constant BUDGET_WARNING_PCT     = 60;

    mapping(bytes32 => bool) public allowedRegions;

    address public ethicsCommittee;

    /// @notice Core judicial audit log event corresponding to GeneEvi function
    event LogJudicialEvidence(
        uint256 indexed blockTimestamp,
        uint256 indexed blockNumber,
        address indexed violatingParty,
        string  violationType,
        string  clauseId,
        bytes32 evidenceHash,
        string  nlFactStatement,
        bytes32 oracleDataHash
    );

    /// @notice Privacy budget consumption event
    event BudgetConsumed(
        address indexed caller,
        uint256 cost,
        uint256 bRemAfter,
        uint8   pricingZone
    );

    /// @notice State machine transition event
    event StateTransition(
        ContractState indexed fromState,
        ContractState indexed toState,
        string  reason,
        uint256 timestamp
    );

    /// @notice Three-phase procedural justice events
    event AssetFrozen        (address indexed party, uint256 amount, uint256 timestamp);
    event ChallengeWindowOpen(address indexed party, uint256 deadline);
    event AppealReceived    (address indexed party, bytes32 evidenceHash);
    event PenaltyExecuted   (address indexed party, uint256 amount, bytes32 evidenceHash);

    modifier inState(ContractState _state) {
        require(currentState == _state,
            string(abi.encodePacked("Wrong state: expected ",
                _stateToString(_state))));
        _;
    }

    modifier onlyDataOwner() {
        require(msg.sender == dataOwnerSubject.addr, "Caller is not DataOwner");
        _;
    }

    modifier onlyModelProvider() {
        require(msg.sender == modelProviderSubject.addr, "Caller is not ModelProvider");
        _;
    }

    modifier onlyEthicsCommittee() {
        require(msg.sender == ethicsCommittee, "Caller is not EthicsCommittee");
        _;
    }

    modifier notBreached() {
        require(currentState != ContractState.Breach &&
                currentState != ContractState.Resolved,
            "Contract is terminated");
        _;
    }

    /**
     * @notice Initialize the SLCML contract with quintuple parameters
     * @param _dataOwner        Data provider address
     * @param _modelProvider    Model trainer address
     * @param _ethicsCommittee  Multi-signature ethics committee address
     * @param _credHash_DO      Data provider credential hash
     * @param _credHash_MP      Model trainer credential hash
     * @param _assetId          Data asset identifier
     * @param _sensitivityLevel Data sensitivity level (1-5)
     * @param _bTotal           Initial total privacy budget (1e18 units)
     * @param _allowedRegion    Permitted geographic region identifier
     */
    constructor(
        address _dataOwner,
        address _modelProvider,
        address _ethicsCommittee,
        bytes32 _credHash_DO,
        bytes32 _credHash_MP,
        bytes32 _assetId,
        uint8   _sensitivityLevel,
        uint256 _bTotal,
        string  memory _allowedRegion
    ) payable {
        require(_dataOwner     != address(0), "Invalid DataOwner address");
        require(_modelProvider != address(0), "Invalid ModelProvider address");
        require(_sensitivityLevel >= 1 && _sensitivityLevel <= 5,
            "Sensitivity level must be 1-5");
        require(_bTotal > 0, "Total budget must be positive");

        dataOwnerSubject = Subject({
            addr:           _dataOwner,
            credentialHash: _credHash_DO,
            reputation:     REPUTATION_INITIAL,
            callCount:      0,
            isRegistered:   true
        });

        modelProviderSubject = Subject({
            addr:           _modelProvider,
            credentialHash: _credHash_MP,
            reputation:     REPUTATION_INITIAL,
            callCount:      0,
            isRegistered:   true
        });

        ethicsCommittee = _ethicsCommittee;

        dataAsset = DataAsset({
            assetId:          _assetId,
            sensitivityLevel: _sensitivityLevel,
            bTotal:           _bTotal,
            bRem:             _bTotal,
            dataRegion:       _allowedRegion
        });

        allowedRegions[keccak256(abi.encodePacked(_allowedRegion))] = true;

        depositBalance = msg.value;

        currentState = ContractState.Active;
    }

    /**
     * @notice Data access request entry point — Algorithm 1 implementation
     * @dev    Three-tier pricing: >60% linear, 10%-60% exponential, <10% circuit breaker
     * @param  _requestedSensitivity  Requested data sensitivity level
     * @return authorized             Whether access is granted
     * @return costConsumed           Privacy budget consumed
     */
    function requestData(uint8 _requestedSensitivity)
        external
        notBreached
        onlyModelProvider
        returns (bool authorized, uint256 costConsumed)
    {
        require(_requestedSensitivity <= dataAsset.sensitivityLevel,
            "Requested sensitivity exceeds asset level");

        uint256 n = modelProviderSubject.callCount;

        uint256 criticalThreshold = (dataAsset.bTotal * BUDGET_CRITICAL_PCT) / 100;
        uint256 warningThreshold  = (dataAsset.bTotal * BUDGET_WARNING_PCT)  / 100;

        if (dataAsset.bRem < criticalThreshold) {
            _decreaseReputation(modelProviderSubject, REPUTATION_PENALTY_STEP * 2);
            emit BudgetConsumed(msg.sender, 0, dataAsset.bRem, 2);
            revert("SLCML: Budget Exhausted - Physical Fuse Triggered");
        }

        uint256 cost;

        if (dataAsset.bRem <= warningThreshold) {
            cost = _computeExponentialCost(_requestedSensitivity, n);
            emit BudgetConsumed(msg.sender, cost, dataAsset.bRem, 1);
            _decreaseReputation(modelProviderSubject, REPUTATION_PENALTY_STEP);
        }
        else {
            cost = uint256(_requestedSensitivity) * 1e18;
            emit BudgetConsumed(msg.sender, cost, dataAsset.bRem, 0);
        }

        if (dataAsset.bRem < cost) {
            emit BudgetConsumed(msg.sender, cost, dataAsset.bRem, 2);
            revert("SLCML: Insufficient budget for this request");
        }

        dataAsset.bRem -= cost;
        modelProviderSubject.callCount += 1;

        if (dataAsset.bRem <= warningThreshold &&
            currentState == ContractState.Active) {
            _transitionState(ContractState.RiskWarning,
                "Privacy budget entered warning zone");
        }

        return (true, cost);
    }

    /**
     * @dev    Exponential penalty cost computation using PRBMath SD59x18
     *         cost = Level_sens * exp(alpha * n), alpha = 0.1
     * @param  _level  Data sensitivity level (1-5)
     * @param  _n      Subject historical call frequency
     * @return cost    Budget consumption in 1e18 precision
     */
    function _computeExponentialCost(uint8 _level, uint256 _n)
        internal
        pure
        returns (uint256 cost)
    {
        SD59x18 alpha = sd(1e17);
        SD59x18 nSD   = convert(int256(_n));
        SD59x18 exponent = alpha.mul(nSD);
        SD59x18 expVal   = exponent.exp();

        SD59x18 levelSD  = convert(int256(uint256(_level)));

        SD59x18 unitSD   = sd(int256(1e18));
        SD59x18 costSD   = levelSD.mul(expVal).mul(unitSD);

        int256 costInt = SD59x18.unwrap(costSD);
        require(costInt > 0, "SLCML: Cost computation underflow");
        cost = uint256(costInt);
    }

    /**
     * @notice Receive oracle callback and initiate procedural accountability — Algorithm 2
     * @dev    Detects Geographic_Breach and Performance_Breach, transitions to Challenge state,
     *         freezes assets, opens 72-hour challenge window.
     * @param _violationType   Violation type string
     * @param _clauseId        Natural language contract clause index
     * @param _oraclePayload   Keccak256 hash of oracle raw data
     */
    function receiveOracleData(
        string  memory _violationType,
        string  memory _clauseId,
        bytes32        _oraclePayload
    )
        external
        notBreached
    {
        require(
            msg.sender == dataOwnerSubject.addr ||
            msg.sender == ethicsCommittee,
            "SLCML: Unauthorized oracle caller"
        );

        require(bytes(_violationType).length > 0, "SLCML: Empty violation type");

        bytes32 vTypeHash = keccak256(abi.encodePacked(_violationType));
        require(
            vTypeHash == keccak256("Geographic_Breach")   ||
            vTypeHash == keccak256("Performance_Breach")  ||
            vTypeHash == keccak256("DataPrivacy_Breach"),
            "SLCML: Unknown violation type"
        );

        _transitionState(ContractState.Challenge,
            string(abi.encodePacked("Oracle detected: ", _violationType)));

        challengeStartTime    = block.timestamp;
        pendingViolationType  = _violationType;
        pendingClauseId       = _clauseId;
        pendingOracleHash     = _oraclePayload;
        appealSubmitted       = false;

        emit AssetFrozen(modelProviderSubject.addr, depositBalance, block.timestamp);

        uint256 deadline = block.timestamp + CHALLENGE_WINDOW;
        emit ChallengeWindowOpen(modelProviderSubject.addr, deadline);
    }

    /**
     * @notice Respondent submits appeal evidence within challenge window
     * @dev    Implements the electronic right of defense
     * @param _appealEvidenceHash  Keccak256 hash of off-chain appeal evidence
     */
    function submitAppeal(bytes32 _appealEvidenceHash)
        external
        inState(ContractState.Challenge)
        onlyModelProvider
    {
        require(
            block.timestamp < challengeStartTime + CHALLENGE_WINDOW,
            "SLCML: Challenge window has expired"
        );
        require(!appealSubmitted, "SLCML: Appeal already submitted");

        appealSubmitted = true;
        currentAppeal = AppealRecord({
            evidenceHash: _appealEvidenceHash,
            submitTime:   block.timestamp,
            isRejected:   false
        });

        emit AppealReceived(modelProviderSubject.addr, _appealEvidenceHash);
    }

    /**
     * @notice Ethics committee adjudication: reject appeal, execute final penalty
     * @dev    Algorithm 2: formal rejection branch
     */
    function rejectAppeal()
        external
        inState(ContractState.Challenge)
        onlyEthicsCommittee
    {
        require(appealSubmitted, "SLCML: No appeal to reject");
        currentAppeal.isRejected = true;

        _executeFinalPenalty("Appeal rejected by EthicsCommittee");
    }

    /**
     * @notice Ethics committee adjudication: accept appeal, restore contract
     * @dev    Breach dismissed, unfreeze assets, state rollback to Active
     */
    function acceptAppeal()
        external
        inState(ContractState.Challenge)
        onlyEthicsCommittee
    {
        require(appealSubmitted, "SLCML: No appeal to accept");

        _transitionState(ContractState.Active,
            "Appeal accepted - contract restored");
        delete pendingViolationType;
        delete pendingClauseId;
        pendingOracleHash = bytes32(0);
        appealSubmitted   = false;
    }

    /**
     * @notice Execute final penalty after challenge window timeout
     * @dev    Algorithm 2: timeout expiration branch
     */
    function executePenaltyAfterTimeout() external inState(ContractState.Challenge) {
        require(
            block.timestamp >= challengeStartTime + CHALLENGE_WINDOW,
            "SLCML: Challenge window still open"
        );
        _executeFinalPenalty("Challenge window expired without valid appeal");
    }

    /**
     * @dev    Final adjudication and judicial evidence generation (GeneEvi)
     *         Algorithm 2 Steps 14-20: state transition, penalty execution,
     *         NL template filling, evidence hash computation, event emission.
     */
    function _executeFinalPenalty(string memory _adjudicationReason) internal {
        _transitionState(ContractState.Breach, _adjudicationReason);

        uint256 penaltyAmount = depositBalance;
        depositBalance = 0;
        
        if (penaltyAmount > 0) {
            (bool success, ) = dataOwnerSubject.addr.call{value: penaltyAmount}("");
            require(success, "SLCML: Penalty transfer failed");
        }

        string memory nlFact = _fillNLTemplate(
            block.timestamp,
            modelProviderSubject.addr,
            pendingViolationType,
            pendingClauseId,
            penaltyAmount
        );

        bytes32 evidenceHash = keccak256(abi.encodePacked(
            block.timestamp,
            block.number,
            modelProviderSubject.addr,
            pendingViolationType,
            pendingClauseId,
            pendingOracleHash,
            nlFact,
            penaltyAmount
        ));

        emit LogJudicialEvidence(
            block.timestamp,
            block.number,
            modelProviderSubject.addr,
            pendingViolationType,
            pendingClauseId,
            evidenceHash,
            nlFact,
            pendingOracleHash
        );

        emit PenaltyExecuted(modelProviderSubject.addr, penaltyAmount, evidenceHash);

        _decreaseReputation(modelProviderSubject, REPUTATION_PENALTY_STEP * 4);

        delete pendingViolationType;
        delete pendingClauseId;
        pendingOracleHash = bytes32(0);
    }

    /**
     * @dev Natural language template filling — injects runtime variables into
     *      pre-compiled court-readable evidence statement template.
     */
    function _fillNLTemplate(
        uint256 _timestamp,
        address _party,
        string  memory _violationType,
        string  memory _clauseId,
        uint256 _penalty
    )
        internal
        pure
        returns (string memory)
    {
        return string(abi.encodePacked(
            "JUDICIAL EVIDENCE STATEMENT | ",
            "At block timestamp [", _uintToString(_timestamp), "], ",
            "as certified by the on-chain Oracle, ",
            "Party [", _addressToString(_party), "] ",
            "committed a violation of type [", _violationType, "], ",
            "in breach of Contract ", _clauseId, ". ",
            "Pursuant to the Freeze-Challenge-Adjudication procedure, ",
            "a penalty of [", _uintToString(_penalty), " units] ",
            "has been executed and permanently recorded on-chain."
        ));
    }

    /// @dev Unified state machine transition with event emission
    function _transitionState(ContractState _newState, string memory _reason) internal {
        ContractState oldState = currentState;
        currentState = _newState;
        emit StateTransition(oldState, _newState, _reason, block.timestamp);
    }

    /// @dev Reputation deduction with underflow protection
    function _decreaseReputation(Subject storage _subject, uint256 _amount) internal {
        if (_subject.reputation >= _amount) {
            _subject.reputation -= _amount;
        } else {
            _subject.reputation = 0;
        }
    }

    /// @dev uint256 to string conversion
    function _uintToString(uint256 _v) internal pure returns (string memory) {
        if (_v == 0) return "0";
        uint256 temp = _v;
        uint256 digits;
        while (temp != 0) { digits++; temp /= 10; }
        bytes memory buffer = new bytes(digits);
        while (_v != 0) {
            digits--;
            buffer[digits] = bytes1(uint8(48 + uint256(_v % 10)));
            _v /= 10;
        }
        return string(buffer);
    }

    /// @dev Address to hexadecimal string conversion
    function _addressToString(address _addr) internal pure returns (string memory) {
        bytes memory data = abi.encodePacked(_addr);
        bytes memory hexAlpha = "0123456789abcdef";
        bytes memory str = new bytes(2 + data.length * 2);
        str[0] = "0";
        str[1] = "x";
        for (uint256 i = 0; i < data.length; i++) {
            str[2 + i * 2]     = hexAlpha[uint8(data[i] >> 4)];
            str[3 + i * 2]     = hexAlpha[uint8(data[i] & 0x0f)];
        }
        return string(str);
    }

    /// @dev ContractState enum to readable string
    function _stateToString(ContractState _s) internal pure returns (string memory) {
        if (_s == ContractState.Active)      return "Active";
        if (_s == ContractState.RiskWarning) return "RiskWarning";
        if (_s == ContractState.Challenge)   return "Challenge";
        if (_s == ContractState.Breach)      return "Breach";
        return "Resolved";
    }

    /// @notice Get total evidence log entry count
    function getEvidenceCount() external view returns (uint256) {
        return evidenceLog.length;
    }

    /**
     * @notice Retrieve a single judicial evidence record by index
     * @param  _index Evidence array index
     * @return Complete JudicialEvidence struct
     */
    function getEvidence(uint256 _index)
        external
        view
        returns (JudicialEvidence memory)
    {
        require(_index < evidenceLog.length, "SLCML: Evidence index out of bounds");
        return evidenceLog[_index];
    }

    /// @notice Get the latest evidence hash anchor for independent verification
    function getLatestEvidenceHash() external view returns (bytes32) {
        require(evidenceLog.length > 0, "SLCML: No evidence recorded yet");
        return evidenceLog[evidenceLog.length - 1].evidenceHash;
    }

    /**
     * @notice Get complete contract state snapshot
     * @return state            Current FSM state
     * @return bRem             Remaining privacy budget
     * @return bTotal           Initial total budget
     * @return budgetPct        Remaining budget percentage (x100)
     * @return mpReputation     Model provider current reputation
     * @return mpCallCount      Model provider historical call count
     * @return deposit          Current frozen deposit balance
     * @return challengeDeadline Challenge period deadline (0 if not in challenge)
     */
    function getContractSnapshot()
        external
        view
        returns (
            string  memory state,
            uint256 bRem,
            uint256 bTotal,
            uint256 budgetPct,
            uint256 mpReputation,
            uint256 mpCallCount,
            uint256 deposit,
            uint256 challengeDeadline
        )
    {
        state        = _stateToString(currentState);
        bRem         = dataAsset.bRem;
        bTotal       = dataAsset.bTotal;
        budgetPct    = (dataAsset.bRem * 100) / dataAsset.bTotal;
        mpReputation = modelProviderSubject.reputation;
        mpCallCount  = modelProviderSubject.callCount;
        deposit      = depositBalance;
        challengeDeadline = (currentState == ContractState.Challenge)
            ? (challengeStartTime + CHALLENGE_WINDOW)
            : 0;
    }

    /**
     * @notice Verify if a geographic region is in the allowlist
     * @param  _region Region string identifier
     * @return bool
     */
    function isRegionAllowed(string memory _region) external view returns (bool) {
        return allowedRegions[keccak256(abi.encodePacked(_region))];
    }

    /// @notice Get data asset properties
    function getDataAsset() external view returns (DataAsset memory) {
        return dataAsset;
    }

    /// @notice Get data owner subject information
    function getDataOwnerInfo() external view returns (Subject memory) {
        return dataOwnerSubject;
    }

    /// @notice Get model provider subject information
    function getModelProviderInfo() external view returns (Subject memory) {
        return modelProviderSubject;
    }

    /**
     * @notice Add a permitted geographic region to the allowlist
     * @param  _region New permitted region identifier
     */
    function addAllowedRegion(string memory _region)
        external
        onlyDataOwner
        notBreached
    {
        allowedRegions[keccak256(abi.encodePacked(_region))] = true;
    }

    /// @notice Mark contract as Resolved after full adjudication
    function markResolved()
        external
        onlyEthicsCommittee
        inState(ContractState.Breach)
    {
        _transitionState(ContractState.Resolved, "Contract fully adjudicated");
    }

    /// @notice Accept ETH deposit
    receive() external payable {
        depositBalance += msg.value;
    }
}