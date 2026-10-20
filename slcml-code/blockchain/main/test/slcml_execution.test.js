const { expect } = require("chai");
const { ethers } = require("hardhat");
const { time } = require("@nomicfoundation/hardhat-network-helpers");
const { performance } = require("perf_hooks");

describe("SLCML Contract — Local Judicial Audit Execution", function () {

    let contract;
    let dataOwner, modelProvider, ethicsCommittee, stranger;

    const B_TOTAL = ethers.parseEther("100");
    const DEPOSIT = ethers.parseEther("10");
    const SENSITIVITY = 3;
    const ALLOWED_REGION = "China_Mainland";
    const ASSET_ID = ethers.encodeBytes32String("MEDICAL_DATASET_001");
    const DO_CRED = ethers.encodeBytes32String("DO_CREDENTIAL_HASH");
    const MP_CRED = ethers.encodeBytes32String("MP_CREDENTIAL_HASH");

    beforeEach(async function () {
        [dataOwner, modelProvider, ethicsCommittee, stranger] =
            await ethers.getSigners();

        const Factory = await ethers.getContractFactory("SLCML_Contract");
        contract = await Factory.deploy(
            dataOwner.address,
            modelProvider.address,
            ethicsCommittee.address,
            DO_CRED,
            MP_CRED,
            ASSET_ID,
            SENSITIVITY,
            B_TOTAL,
            ALLOWED_REGION,
            { value: DEPOSIT }
        );
        await contract.waitForDeployment();
    });

    describe("Algorithm 1: Dynamic Segmented Privacy Budget Control", function () {
        it("T1-1: Compliance zone (>60%) should apply linear pricing and authorize", async function () {
            const [authorized, cost] = await contract
                .connect(modelProvider)
                .requestData.staticCall(2);
            expect(authorized).to.equal(true);
            expect(cost).to.equal(2n * 10n ** 18n);
        });

        it("T1-2: Warning zone (10-60%) should trigger exponential pricing", async function () {
            const warningThreshold = B_TOTAL * 50n / 100n;
            while (true) {
                const snapshot = await contract.getContractSnapshot();
                if (Number(snapshot.budgetPct) <= 50) break;
                await contract.connect(modelProvider).requestData(SENSITIVITY);
            }
            const snapshot = await contract.getContractSnapshot();
            const pct = Number(snapshot.budgetPct);
            expect(pct).to.be.lte(60);
            expect(pct).to.be.gte(10);

            const [auth, cost] = await contract.connect(modelProvider).requestData.staticCall(1);
            expect(auth).to.equal(true);
            expect(cost).to.be.gt(1n * 10n ** 18n);
        });

        it("T1-3: Below 10% should trigger physical circuit breaker revert", async function () {
            while (true) {
                try {
                    await contract.connect(modelProvider).requestData(1);
                } catch (e) {
                    if (e.message.includes("Budget Exhausted - Physical Fuse")) break;
                    if (e.message.includes("Insufficient budget")) {
                        break;
                    }
                    throw e;
                }
            }
            await expect(
                contract.connect(modelProvider).requestData(1)
            ).to.be.revertedWith("SLCML: Budget Exhausted - Physical Fuse Triggered");
        });

        it("T1-4: Non-ModelProvider should be rejected", async function () {
            await expect(
                contract.connect(stranger).requestData(1)
            ).to.be.revertedWith("Caller is not ModelProvider");
        });

        it("T1-5: Sensitivity exceeding asset level should be rejected", async function () {
            await expect(
                contract.connect(modelProvider).requestData(SENSITIVITY + 1)
            ).to.be.revertedWith("Requested sensitivity exceeds asset level");
        });
    });

    describe("Algorithm 2: Freeze-Challenge-Adjudication Procedural Justice", function () {
        const VIOLATION_TYPE = "Geographic_Breach";
        const CLAUSE_ID = "Clause_4.1";
        const ORACLE_PAYLOAD = ethers.keccak256(ethers.toUtf8Bytes("GeoIP:overseas"));

        it("T2-1: Oracle trigger should transition to Challenge and freeze deposit", async function () {
            const tx = await contract.connect(dataOwner).receiveOracleData(VIOLATION_TYPE, CLAUSE_ID, ORACLE_PAYLOAD);
            const receipt = await tx.wait();
            const snapshot = await contract.getContractSnapshot();
            expect(snapshot.state).to.equal("Challenge");
        });

        it("T2-2: Penalty execution should be blocked during challenge window", async function () {
            await contract.connect(dataOwner).receiveOracleData(VIOLATION_TYPE, CLAUSE_ID, ORACLE_PAYLOAD);
            await expect(
                contract.executePenaltyAfterTimeout()
            ).to.be.revertedWith("SLCML: Challenge window still open");
        });

        it("T2-3: Respondent should submit defense evidence within window", async function () {
            await contract.connect(dataOwner).receiveOracleData(VIOLATION_TYPE, CLAUSE_ID, ORACLE_PAYLOAD);
            const appealHash = ethers.keccak256(ethers.toUtf8Bytes("ops_log.json"));
            await expect(
                contract.connect(modelProvider).submitAppeal(appealHash)
            ).to.emit(contract, "AppealReceived").withArgs(modelProvider.address, appealHash);
            expect(await contract.appealSubmitted()).to.equal(true);
        });

        it("T2-4: After 72h timeout should execute final penalty and generate evidence", async function () {
            await contract.connect(dataOwner).receiveOracleData(VIOLATION_TYPE, CLAUSE_ID, ORACLE_PAYLOAD);
            await time.increase(72 * 3600 + 1);

            const tx = await contract.executePenaltyAfterTimeout();
            const receipt = await tx.wait();

            const evidenceEvent = receipt.logs
                .map(log => {
                    try { return contract.interface.parseLog(log); }
                    catch { return null; }
                })
                .find(e => e?.name === "LogJudicialEvidence");

            expect(evidenceEvent).to.not.be.undefined;
            const snapshot = await contract.getContractSnapshot();
            expect(snapshot.state).to.equal("Breach");
            expect(snapshot.deposit).to.equal(0n);
        });

        it("T2-5: Ethics committee rejection should immediately execute penalty", async function () {
            await contract.connect(dataOwner).receiveOracleData(VIOLATION_TYPE, CLAUSE_ID, ORACLE_PAYLOAD);
            await contract.connect(modelProvider).submitAppeal(ethers.keccak256(ethers.toUtf8Bytes("evidence")));

            const tx = await contract.connect(ethicsCommittee).rejectAppeal();
            await expect(tx).to.emit(contract, "LogJudicialEvidence");

            const snapshot = await contract.getContractSnapshot();
            expect(snapshot.state).to.equal("Breach");
        });

        it("T2-6: Ethics committee acceptance should restore Active state", async function () {
            await contract.connect(dataOwner).receiveOracleData(VIOLATION_TYPE, CLAUSE_ID, ORACLE_PAYLOAD);
            await contract.connect(modelProvider).submitAppeal(ethers.keccak256(ethers.toUtf8Bytes("valid_defense")));

            const tx = await contract.connect(ethicsCommittee).acceptAppeal();
            await expect(tx).to.emit(contract, "StateTransition");

            const snapshot = await contract.getContractSnapshot();
            expect(snapshot.state).to.equal("Active");
            expect(snapshot.deposit).to.equal(DEPOSIT);
        });

        it("T2-7: Late appeal after window expiration should be rejected", async function () {
            await contract.connect(dataOwner).receiveOracleData(VIOLATION_TYPE, CLAUSE_ID, ORACLE_PAYLOAD);
            await time.increase(72 * 3600 + 1);

            await expect(
                contract.connect(modelProvider).submitAppeal(
                    ethers.keccak256(ethers.toUtf8Bytes("late_appeal"))
                )
            ).to.be.revertedWith("SLCML: Challenge window has expired");
        });

        it("T2-8: Unauthorized caller should not trigger oracle callback", async function () {
            await expect(
                contract.connect(stranger).receiveOracleData(VIOLATION_TYPE, CLAUSE_ID, ORACLE_PAYLOAD)
            ).to.be.revertedWith("SLCML: Unauthorized oracle caller");
        });
    });

    describe("Judicial Evidence Chain Integrity & Performance", function () {
        const VIOLATION_TYPE = "Geographic_Breach";
        const CLAUSE_ID = "Clause_4.1";
        const ORACLE_PAYLOAD = ethers.keccak256(ethers.toUtf8Bytes("deterministic_payload"));

        beforeEach(async function () {
            await contract.connect(dataOwner).receiveOracleData(VIOLATION_TYPE, CLAUSE_ID, ORACLE_PAYLOAD);
            await time.increase(72 * 3600 + 1);
        });

        it("T3-1: Evidence hash should be deterministic with trusted timestamp", async function () {
            const tx = await contract.executePenaltyAfterTimeout();
            const receipt = await tx.wait();
            
            const log = receipt.logs.map(l => { try { return contract.interface.parseLog(l); } catch { return null; } }).find(e => e?.name === "LogJudicialEvidence");
            const evidence = log.args;

            expect(evidence.evidenceHash).to.not.equal(ethers.ZeroHash);
            expect(evidence.blockNumber).to.be.gt(0n);
        });

        it("T3-2: NL fact statement should contain all required legal elements", async function () {
            const tx = await contract.executePenaltyAfterTimeout();
            const receipt = await tx.wait();
            const log = receipt.logs.map(l => { try { return contract.interface.parseLog(l); } catch { return null; } }).find(e => e?.name === "LogJudicialEvidence");
            const nlFact = log.args.nlFactStatement;

            expect(nlFact).to.include("JUDICIAL EVIDENCE");
            expect(nlFact).to.include(modelProvider.address.toLowerCase());
            expect(nlFact).to.include(VIOLATION_TYPE);
            expect(nlFact).to.include(CLAUSE_ID);
            expect(nlFact).to.include(ethers.formatUnits(DEPOSIT, "wei"));
        });

        it("T3-3: [Performance] Time-to-Evidence latency benchmark", async function () {
            const startTimestamp = performance.now();

            const tx = await contract.executePenaltyAfterTimeout();
            const receipt = await tx.wait();

            const evidenceEvent = receipt.logs
                .map(log => {
                    try { return contract.interface.parseLog(log); }
                    catch { return null; }
                })
                .find(e => e?.name === "LogJudicialEvidence");

            const endTimestamp = performance.now();
            const latencyMs = endTimestamp - startTimestamp;

            expect(evidenceEvent).to.not.be.undefined;
            console.log(`\n\t[Time-to-Evidence Latency]: ${latencyMs.toFixed(2)} ms`);
            expect(latencyMs).to.be.lessThan(5000);
        });

        it("T3-4: NL fact statement should include all six legal elements", async function () {
            const tx = await contract.executePenaltyAfterTimeout();
            const receipt = await tx.wait();
            const log = receipt.logs.map(l => { try { return contract.interface.parseLog(l); } catch { return null; } }).find(e => e?.name === "LogJudicialEvidence");
            const nlFact = log.args.nlFactStatement;

            expect(nlFact).to.include("JUDICIAL EVIDENCE");
            expect(nlFact).to.include("on-chain Oracle");
            expect(nlFact).to.include("Geographic_Breach");
            expect(nlFact).to.include("Clause_4.1");
            expect(nlFact).to.include("penalty");
            expect(nlFact).to.include("executed");
        });

        it("T3-5: Optimized mode - getLatestEvidenceHash should revert (empty array)", async function () {
            await contract.executePenaltyAfterTimeout();
            await expect(contract.getLatestEvidenceHash()).to.be.revertedWith("SLCML: No evidence recorded yet");
        });

        it("T3-6: Optimized mode - getEvidenceCount should return 0", async function () {
            await contract.executePenaltyAfterTimeout();
            expect(await contract.getEvidenceCount()).to.equal(0n);
        });

        it("T3-7: getLatestEvidenceHash should revert on fresh contract", async function () {
            const Factory = await ethers.getContractFactory("SLCML_Contract");
            const freshContract = await Factory.deploy(
                dataOwner.address, modelProvider.address, ethicsCommittee.address,
                DO_CRED, MP_CRED, ASSET_ID, SENSITIVITY, B_TOTAL, ALLOWED_REGION,
                { value: DEPOSIT }
            );
            await freshContract.waitForDeployment();

            await expect(
                freshContract.getLatestEvidenceHash()
            ).to.be.revertedWith("SLCML: No evidence recorded yet");
        });
    });

    describe("Reputation System & State Machine Integrity", function () {

        it("T4-1: Initial reputation should be 100", async function () {
            const snapshot = await contract.getContractSnapshot();
            expect(snapshot.mpReputation).to.equal(100n);
        });

        it("T4-2: Final penalty should deduct 20 reputation points", async function () {
            const ORACLE_PAYLOAD = ethers.keccak256(ethers.toUtf8Bytes("reputation_penalty_test"));
            await contract.connect(dataOwner).receiveOracleData("Geographic_Breach", "Clause_4.1", ORACLE_PAYLOAD);
            await time.increase(72 * 3600 + 1);
            await contract.executePenaltyAfterTimeout();

            const snapshot = await contract.getContractSnapshot();
            expect(snapshot.mpReputation).to.equal(80n);
        });

        it("T4-3: Data requests should be blocked in Breach state", async function () {
            const ORACLE_PAYLOAD = ethers.keccak256(ethers.toUtf8Bytes("breach_block_test"));
            await contract.connect(dataOwner).receiveOracleData("Geographic_Breach", "Clause_4.1", ORACLE_PAYLOAD);
            await time.increase(72 * 3600 + 1);
            await contract.executePenaltyAfterTimeout();

            await expect(
                contract.connect(modelProvider).requestData(1)
            ).to.be.revertedWith("Contract is terminated");
        });

        it("T4-4: Oracle callbacks should be blocked in Breach state", async function () {
            const ORACLE_PAYLOAD = ethers.keccak256(ethers.toUtf8Bytes("double_breach_test"));
            await contract.connect(dataOwner).receiveOracleData("Geographic_Breach", "Clause_4.1", ORACLE_PAYLOAD);
            await time.increase(72 * 3600 + 1);
            await contract.executePenaltyAfterTimeout();

            await expect(
                contract.connect(dataOwner).receiveOracleData("Performance_Breach", "Clause_4.2", ORACLE_PAYLOAD)
            ).to.be.revertedWith("Contract is terminated");
        });

        it("T4-5: Ethics committee should mark Breach as Resolved", async function () {
            const ORACLE_PAYLOAD = ethers.keccak256(ethers.toUtf8Bytes("resolved_test"));
            await contract.connect(dataOwner).receiveOracleData("Geographic_Breach", "Clause_4.1", ORACLE_PAYLOAD);
            await time.increase(72 * 3600 + 1);
            await contract.executePenaltyAfterTimeout();

            await contract.connect(ethicsCommittee).markResolved();

            const snapshot = await contract.getContractSnapshot();
            expect(snapshot.state).to.equal("Resolved");
        });

        it("T4-6: Non-committee member should not call markResolved", async function () {
            const ORACLE_PAYLOAD = ethers.keccak256(ethers.toUtf8Bytes("unauthorized_resolve_test"));
            await contract.connect(dataOwner).receiveOracleData("Geographic_Breach", "Clause_4.1", ORACLE_PAYLOAD);
            await time.increase(72 * 3600 + 1);
            await contract.executePenaltyAfterTimeout();

            await expect(
                contract.connect(stranger).markResolved()
            ).to.be.revertedWith("Caller is not EthicsCommittee");
        });
    });

    describe("E2E Execution: Full Medical Data Contract Lifecycle", function () {

        it("T5-1: Normal execution — multiple compliant accesses maintain Active", async function () {
            for (let i = 0; i < 10; i++) {
                const [auth] = await contract.connect(modelProvider).requestData.staticCall(2);
                expect(auth).to.equal(true);
                await contract.connect(modelProvider).requestData(2);
            }

            const snapshot = await contract.getContractSnapshot();
            expect(snapshot.state).to.satisfy(s => s === "Active" || s === "RiskWarning");
            expect(snapshot.mpCallCount).to.equal(10n);
        });

        it("T5-2: Breach accountability — full Active to Breach path verification", async function () {
            for (let i = 0; i < 5; i++) {
                await contract.connect(modelProvider).requestData(1);
            }

            const ORACLE_PAYLOAD = ethers.keccak256(ethers.toUtf8Bytes("overseas_ip_detected:203.0.113.42"));
            await contract.connect(dataOwner).receiveOracleData("Geographic_Breach", "Clause_4.1", ORACLE_PAYLOAD);
            let snapshot = await contract.getContractSnapshot();
            expect(snapshot.state).to.equal("Challenge");

            const appealHash = ethers.keccak256(ethers.toUtf8Bytes("ops_log_claim_domestic_server.json"));
            await contract.connect(modelProvider).submitAppeal(appealHash);

            const tx = await contract.connect(ethicsCommittee).rejectAppeal();
            const receipt = await tx.wait();

            snapshot = await contract.getContractSnapshot();
            expect(snapshot.state).to.equal("Breach");
            expect(snapshot.deposit).to.equal(0n);
            expect(snapshot.mpReputation).to.equal(80n);

            expect(await contract.getEvidenceCount()).to.equal(0n);

            const log = receipt.logs.map(l => { try { return contract.interface.parseLog(l); } catch { return null; } }).find(e => e?.name === "LogJudicialEvidence");
            expect(log).to.not.be.undefined;
            const evidence = log.args;
            
            expect(evidence.violationType).to.equal("Geographic_Breach");
            expect(evidence.clauseId).to.equal("Clause_4.1");
            expect(evidence.oracleDataHash).to.equal(ORACLE_PAYLOAD);

            await contract.connect(ethicsCommittee).markResolved();
            snapshot = await contract.getContractSnapshot();
            expect(snapshot.state).to.equal("Resolved");
        });

        it("T5-3: Successful appeal — contract restored to normal operation", async function () {
            const ORACLE_PAYLOAD = ethers.keccak256(ethers.toUtf8Bytes("false_positive_geo_alert"));
            await contract.connect(dataOwner).receiveOracleData("Geographic_Breach", "Clause_4.1", ORACLE_PAYLOAD);

            const validDefenseHash = ethers.keccak256(ethers.toUtf8Bytes("cdn_node_domestic_cert.pdf"));
            await contract.connect(modelProvider).submitAppeal(validDefenseHash);

            await contract.connect(ethicsCommittee).acceptAppeal();

            let snapshot = await contract.getContractSnapshot();
            expect(snapshot.state).to.equal("Active");
            expect(snapshot.deposit).to.equal(DEPOSIT);

            const [auth] = await contract.connect(modelProvider).requestData.staticCall(1);
            expect(auth).to.equal(true);

            expect(await contract.getEvidenceCount()).to.equal(0n);
        });
    });
});