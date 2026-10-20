const path = require("path");
const fs = require("fs");
const crypto = require("crypto");
const hhRequire = require;
const { expect } = hhRequire("chai");
const { ethers, network, artifacts } = hhRequire("hardhat");
const { time } = hhRequire("@nomicfoundation/hardhat-network-helpers");
const OUT = process.env.SLCML_RUN_OUTPUT || path.resolve(__dirname,"../.run");
const CASE = path.resolve(__dirname,"..");
const sourceBytes = fs.readFileSync(path.join(CASE,"source_facts.json"));
const sourceHash = ethers.keccak256(sourceBytes);
const caseId = ethers.encodeBytes32String("AMB2022-01-AMMT-B6");
const machine = ethers.keccak256(ethers.toUtf8Bytes("AMMT"));
const evidence = ethers.id("test-assertion:nominal-or-injected-record");
const challengeEvidence = ethers.id("test-challenge:offchain-evidence-reference");
const wrong = ethers.id("injected mismatch");
const names = ["ReferenceCandidate","ClaudeCandidate","GeminiCandidate"];
const results = { generated_at:null, network:"Hardhat in-memory EVM", chain_id:31337,
  scope:"actual local EVM execution of manually authored candidate-inspired variants, not raw model performance",
  source_facts_sha256:crypto.createHash("sha256").update(sourceBytes).digest("hex"),
  source_card_keccak256:sourceHash, raw_nist_csv_used:false,
  payloads:"injected test assertions grounded in transcribed public nominal metadata",
  candidates:[], mutation_controls:[] };

function decode(contract,receipt) {
  return receipt.logs.flatMap(log => {
    try {
      const e=contract.interface.parseLog(log);
      if (!e) return [];
      if (e.name==="AuditEvidence") return [{ event:e.name, case_id:e.args.caseId,
        phase:e.args.phase, phase_hash:e.args.phaseHash, clause_index:e.args.clauseId,
        clause_hash:e.args.clauseHash, source_card_hash:e.args.sourceCardHash,
        evidence_hash:e.args.evidenceHash, state:Number(e.args.state),
        block_timestamp:Number(e.args.timestamp),log_index:log.index }];
      if (e.name==="StateTransition") return [{ event:e.name, from:Number(e.args.fromState),
        to:Number(e.args.toState), reason:e.args.reason, block_timestamp:Number(e.args.timestamp),log_index:log.index }];
      if (e.name==="RecordSubmitted") return [{ event:e.name,case_id:e.args.caseId,
        source_card_hash:e.args.sourceCardHash,machine_hash:e.args.machineHash,
        power_w:Number(e.args.laserPowerW),speed_mm_s:Number(e.args.scanSpeedMmS),
        oxygen_ppm:Number(e.args.oxygenPpm),evidence_hash:e.args.evidenceHash,
        metadata_match:e.args.metadataMatch,log_index:log.index }];
      return [];
    } catch { return []; }
  });
}

async function receiptRecord(contract,receipt) {
  const block=await ethers.provider.getBlock(receipt.blockNumber);
  return { transaction_hash:receipt.hash,block_number:receipt.blockNumber,
    block_hash:receipt.blockHash, block_timestamp:block.timestamp,
    contract_address:await contract.getAddress(),status:receipt.status,
    gas_used:Number(receipt.gasUsed),logs:decode(contract,receipt) };
}

after(function () {
  results.generated_at=new Date().toISOString();
  results.toolchain={ node:process.version,hardhat:hhRequire("hardhat/package.json").version,
    ethers:hhRequire("ethers").version,solc:hhRequire("solc").version(),
    optimizer_runs:200,viaIR:true,evm_version:"paris",fixed_initial_chain_time:"2026-10-09T00:00:00Z" };
  fs.mkdirSync(OUT,{recursive:true});
  fs.writeFileSync(path.join(OUT,"execution_results.json"),JSON.stringify(results,null,2)+"\n");
});

for (const name of names) {
  describe(name+" repaired AM case", function () {
    let contract,d,a,r,x,factory,report,current;
    const cases=[];
    const paths={};
    const auditNodes={};
    function test(group,label,fn) {
      it(`[${group}] ${label}`,async function () { await fn(); });
    }
    async function transact(tx,label) {
      const receipt=await (await tx).wait();
      const entry=await receiptRecord(contract,receipt);
      entry.label=label;
      current.receipts.push(entry);
      return entry;
    }
    async function record(patch={},label="record assertion") {
      const v={caseId,sourceHash,machine,power:285,speed:960,oxygen:900,evidence,...patch};
      return transact(contract.connect(r).submitRecord(v.caseId,v.sourceHash,v.machine,
        v.power,v.speed,v.oxygen,v.evidence),label);
    }
    async function hold(patch={power:315}) {
      return record(patch,"injected discrepancy");
    }
    function audit(receipt,phase) {
      const e=receipt.logs.find(l=>l.event==="AuditEvidence" && l.phase===phase);
      expect(e,`missing executed ${phase}`).to.exist;
      expect(e.phase_hash).to.equal(ethers.id(phase));
      expect(e.clause_hash).to.equal(ethers.id(e.clause_index));
      expect(e.evidence_hash).to.not.equal(ethers.ZeroHash);
      expect(e.block_timestamp).to.equal(receipt.block_timestamp);
      return e;
    }
    async function flags(frozen) {
      expect(await contract.testReleaseFrozen()).to.equal(frozen);
      expect(await contract.testDepositFrozen()).to.equal(frozen);
    }
    async function rejected(patch,clause,key) {
      const first=await hold(patch);
      expect(await contract.currentState()).to.equal(2n);
      await flags(true);
      expect(first.logs.filter(l=>l.event==="StateTransition").map(l=>[l.from,l.to]))
        .to.deep.equal([[0,1],[1,2]]);
      const firstAudit=audit(first,"freeze");
      expect(firstAudit.state).to.equal(1);
      expect(firstAudit.clause_index).to.equal(clause);
      expect(firstAudit.case_id).to.equal(patch.caseId || caseId);
      expect(firstAudit.source_card_hash).to.equal(patch.sourceHash || sourceHash);
      expect(firstAudit.evidence_hash).to.equal(evidence);
      const second=await transact(contract.connect(a).submitChallenge(challengeEvidence),"analyst challenge");
      const secondAudit=audit(second,"challenge_submitted");
      expect(secondAudit.state).to.equal(2);
      expect(secondAudit.evidence_hash).to.equal(challengeEvidence);
      const third=await transact(contract.connect(r).rejectChallenge(),"reviewer rejects");
      const thirdAudit=audit(third,"breach_confirmed");
      expect(thirdAudit.state).to.equal(3);
      expect(thirdAudit.evidence_hash).to.equal(challengeEvidence);
      [secondAudit,thirdAudit].forEach(e=>{
        expect(e.clause_index).to.equal(clause);
        expect(e.case_id).to.equal(firstAudit.case_id);
        expect(e.source_card_hash).to.equal(firstAudit.source_card_hash);
      });
      expect(await contract.currentState()).to.equal(3n);
      await flags(true);
      expect(first.block_number).to.be.lessThan(second.block_number);
      expect(second.block_number).to.be.lessThan(third.block_number);
      paths[key]={freeze:true,challenge:true,adjudication:true,
        transactions:[first.transaction_hash,second.transaction_hash,third.transaction_hash],
        total_gas:first.gas_used+second.gas_used+third.gas_used};
      if (key==="metadata") {
        auditNodes.freeze=firstAudit;
        auditNodes.challenge_submission=secondAudit;
        auditNodes.disposition=thirdAudit;
      }
    }
    before(async function () {
      await network.provider.send("hardhat_reset");
      [d,a,r,x]=await ethers.getSigners();
      factory=await ethers.getContractFactory(name);
      report={name,tests:cases,deployments:[],logic_checks:[],procedure_paths:paths,
        fixed_audit_nodes:auditNodes,metrics:null};
      const artifact=await artifacts.readArtifact(name);
      report.creation_bytecode_bytes=(artifact.bytecode.length-2)/2;
      report.deployed_bytecode_bytes=(artifact.deployedBytecode.length-2)/2;
      report.creation_bytecode_sha256=crypto.createHash("sha256").update(artifact.bytecode).digest("hex");
      results.candidates.push(report);
    });
    beforeEach(async function () {
      current={title:this.currentTest.title,status:"running",receipts:[],expected_reverts:[]};
      cases.push(current);
      contract=await factory.deploy(d.address,a.address,r.address,caseId,sourceHash,machine);
      await contract.waitForDeployment();
      const rc=await receiptRecord(contract,await contract.deploymentTransaction().wait());
      report.deployments.push({test:this.currentTest.title,...rc});
    });
    afterEach(function () {
      current.status=this.currentTest.state;
      if (this.currentTest.err) current.error=this.currentTest.err.message;
    });
    after(function () {
      for(let i=1;i<=12;i++) {
        const id=`LC${String(i).padStart(2,"0")}`;
        const subset=cases.filter(c=>c.title.startsWith(`[${id}]`));
        report.logic_checks.push({id,n_tests:subset.length,passed:subset.length>0 && subset.every(c=>c.status==="passed")});
      }
      const lc=report.logic_checks.filter(c=>c.passed).length;
      const pc=["provenance","metadata"].flatMap(p=>["freeze","challenge","adjudication"].map(s=>Boolean(paths[p]?.[s]))).filter(Boolean).length;
      const ac=["acceptance","freeze","challenge_submission","disposition"].filter(n=>auditNodes[n]).length;
      report.metrics={LC_AM:{pass:lc,check:12,value:lc/12},
        PC:{pass:pc,check:6,value:pc/6},AC:{covered:ac,nodes:4,value:ac/4},
        Macro_F1:null,reason:"No new extraction gold matching; repaired execution is not extraction evaluation."};
      report.passed_tests=cases.filter(c=>c.status==="passed").length;
      report.total_tests=cases.length;
      report.deployment_gas=report.deployments[0]?.gas_used;
      report.transaction_gas=cases.flatMap(c=>c.receipts.map(rc=>({test:c.title,label:rc.label,gas_used:rc.gas_used})));
    });

    test("LC01","constructor rejects zero and duplicate roles",async()=>{
      await expect(factory.deploy(ethers.ZeroAddress,a.address,r.address,caseId,sourceHash,machine)).to.be.revertedWith("AM: zero address");
      await expect(factory.deploy(d.address,d.address,r.address,caseId,sourceHash,machine)).to.be.revertedWith("AM: roles must differ");
      current.expected_reverts.push("zero address","roles must differ");
    });
    test("LC01","constructor rejects zero registry keys",async()=>{
      for(let i=0;i<3;i++) {
        const keys=[caseId,sourceHash,machine]; keys[i]=ethers.ZeroHash;
        await expect(factory.deploy(d.address,a.address,r.address,...keys)).to.be.revertedWith("AM: zero registry key");
      }
      current.expected_reverts.push("zero registry key, three positions");
    });
    test("LC01","only reviewer can submit assertions",async()=>{
      for(const signer of [d,a,x]) await expect(contract.connect(signer).submitRecord(caseId,sourceHash,machine,285,960,900,evidence))
        .to.be.revertedWith("AM: reviewer only");
      current.expected_reverts.push("unauthorized record callers");
    });
    test("LC02","nominal assertion retains Active and emits complete acceptance evidence",async()=>{
      const receipt=await record();
      const e=audit(receipt,"record_accepted");
      expect(e.case_id).to.equal(caseId); expect(e.clause_index).to.equal("Clause_3.2");
      expect(e.source_card_hash).to.equal(sourceHash); expect(e.evidence_hash).to.equal(evidence);
      expect(e.state).to.equal(0); expect(await contract.currentState()).to.equal(0n);
      await flags(false); auditNodes.acceptance=e;
    });
    test("LC02","wrong build identity freezes under Clause 3.1 rather than reverting",async()=>{
      const receipt=await hold({caseId:wrong});
      expect(audit(receipt,"freeze").clause_index).to.equal("Clause_3.1");
      expect(await contract.currentState()).to.equal(2n);
    });
    test("LC03","wrong source hash is detected",async()=>{
      const receipt=await hold({sourceHash:wrong});
      const e=audit(receipt,"freeze"); expect(e.clause_index).to.equal("Clause_3.1");
      expect(e.source_card_hash).to.equal(wrong);
    });
    test("LC03","wrong machine is detected",async()=>{
      const receipt=await hold({machine:wrong});
      expect(audit(receipt,"freeze").clause_index).to.equal("Clause_3.1");
    });
    for(const power of [284,286,315]) test("LC04",`power ${power} is a metadata discrepancy`,async()=>{
      const receipt=await hold({power}); expect(audit(receipt,"freeze").clause_index).to.equal("Clause_3.2");
    });
    for(const speed of [959,961]) test("LC04",`speed ${speed} is a metadata discrepancy`,async()=>{
      const receipt=await hold({speed}); expect(audit(receipt,"freeze").clause_index).to.equal("Clause_3.2");
    });
    test("LC05","oxygen 999 is accepted",async()=>{
      const receipt=await record({oxygen:999}); audit(receipt,"record_accepted");
      expect(await contract.currentState()).to.equal(0n);
    });
    for(const oxygen of [1000,1001]) test("LC05",`oxygen ${oxygen} fails strict exclusive boundary`,async()=>{
      const receipt=await hold({oxygen}); expect(audit(receipt,"freeze").clause_index).to.equal("Clause_3.2");
      expect(await contract.currentState()).to.equal(2n);
    });
    test("LC06","both hold flags are set before challenge and new records are blocked",async()=>{
      await hold(); await flags(true);
      await expect(contract.connect(r).submitRecord(caseId,sourceHash,machine,285,960,900,evidence)).to.be.revertedWith("AM: record blocked");
      current.expected_reverts.push("record blocked in Challenge");
    });
    test("LC06","simultaneous provenance and metadata mismatch is anchored to provenance first",async()=>{
      const receipt=await hold({sourceHash:wrong,power:315});
      expect(audit(receipt,"freeze").clause_index).to.equal("Clause_3.1");
      await flags(true);
    });
    test("LC07","provenance path executes freeze, challenge, adjudication in order",async()=>{
      await rejected({sourceHash:wrong},"Clause_3.1","provenance");
    });
    test("LC07","metadata path executes freeze, challenge, adjudication with complete audit chain",async()=>{
      await rejected({power:315},"Clause_3.2","metadata");
    });
    test("LC08","challenge is accepted exactly at deadline",async()=>{
      await hold(); const start=await contract.challengeStart();
      await time.setNextBlockTimestamp(start+86400n);
      const receipt=await transact(contract.connect(a).submitChallenge(challengeEvidence),"deadline-boundary challenge");
      audit(receipt,"challenge_submitted"); expect(await contract.challengeSubmitted()).to.equal(true);
    });
    test("LC08","challenge one second after deadline is rejected",async()=>{
      await hold(); const start=await contract.challengeStart();
      await time.setNextBlockTimestamp(start+86401n);
      await expect(contract.connect(a).submitChallenge(challengeEvidence)).to.be.revertedWith("AM: challenge late");
      current.expected_reverts.push("challenge late");
    });
    test("LC09","challenge outside a dispute is blocked",async()=>{
      await expect(contract.connect(a).submitChallenge(challengeEvidence)).to.be.revertedWith("AM: no challenge open");
      current.expected_reverts.push("no challenge open");
    });
    test("LC09","nonzero record and challenge evidence is mandatory",async()=>{
      await expect(contract.connect(r).submitRecord(caseId,sourceHash,machine,285,960,900,ethers.ZeroHash)).to.be.revertedWith("AM: empty evidence");
      await hold();
      await expect(contract.connect(a).submitChallenge(ethers.ZeroHash)).to.be.revertedWith("AM: empty challenge evidence");
      current.expected_reverts.push("empty evidence","empty challenge evidence");
    });
    test("LC09","only analyst may challenge and duplicate challenge is blocked",async()=>{
      await hold();
      for(const signer of [d,r,x]) await expect(contract.connect(signer).submitChallenge(challengeEvidence)).to.be.revertedWith("AM: analyst only");
      await transact(contract.connect(a).submitChallenge(challengeEvidence),"first challenge");
      await expect(contract.connect(a).submitChallenge(wrong)).to.be.revertedWith("AM: challenge already filed");
      expect(await contract.challengeEvidenceHash()).to.equal(challengeEvidence);
      current.expected_reverts.push("analyst only","challenge already filed");
    });
    test("LC10","review cannot precede submission of challenge evidence",async()=>{
      await hold();
      await expect(contract.connect(r).acceptChallenge()).to.be.revertedWith("AM: no evidence filed");
      await expect(contract.connect(r).rejectChallenge()).to.be.revertedWith("AM: no evidence filed");
      current.expected_reverts.push("no evidence filed for both decisions");
    });
    test("LC10","only reviewer may decide a submitted challenge",async()=>{
      await hold(); await transact(contract.connect(a).submitChallenge(challengeEvidence),"challenge");
      for(const signer of [d,a,x]) {
        await expect(contract.connect(signer).acceptChallenge()).to.be.revertedWith("AM: reviewer only");
        await expect(contract.connect(signer).rejectChallenge()).to.be.revertedWith("AM: reviewer only");
      }
      current.expected_reverts.push("reviewer only for both decisions");
    });
    test("LC11","accepted challenge restores both flags without reputation preconditions",async()=>{
      await hold(); await transact(contract.connect(a).submitChallenge(challengeEvidence),"challenge");
      const receipt=await transact(contract.connect(r).acceptChallenge(),"accepted challenge");
      const e=audit(receipt,"challenge_accepted"); expect(e.evidence_hash).to.equal(challengeEvidence);
      expect(e.clause_index).to.equal("Clause_3.2"); expect(e.state).to.equal(4);
      await flags(false); expect(await contract.currentState()).to.equal(4n);
      await expect(contract.connect(r).acceptChallenge()).to.be.revertedWith("AM: no challenge open");
      current.expected_reverts.push("second decision blocked");
    });
    test("LC11","new record after restoration resets all dispute evidence",async()=>{
      await hold(); await transact(contract.connect(a).submitChallenge(challengeEvidence),"challenge");
      await transact(contract.connect(r).acceptChallenge(),"accept");
      const receipt=await hold({machine:wrong});
      expect(audit(receipt,"freeze").clause_index).to.equal("Clause_3.1");
      expect(await contract.challengeSubmitted()).to.equal(false);
      expect(await contract.challengeEvidenceHash()).to.equal(ethers.ZeroHash);
      await flags(true);
    });
    test("LC11","rejected challenge is terminal and both flags stay frozen",async()=>{
      await hold(); await transact(contract.connect(a).submitChallenge(challengeEvidence),"challenge");
      await transact(contract.connect(r).rejectChallenge(),"reject"); await flags(true);
      await expect(contract.connect(r).submitRecord(caseId,sourceHash,machine,285,960,900,evidence)).to.be.revertedWith("AM: record blocked");
      await expect(contract.connect(r).acceptChallenge()).to.be.revertedWith("AM: no challenge open");
      current.expected_reverts.push("records and decisions blocked in Breach");
    });
    test("LC12","timeout at the exact deadline is blocked; after deadline closes only unanswered path",async()=>{
      await hold(); const start=await contract.challengeStart();
      await time.setNextBlockTimestamp(start+86400n);
      await expect(contract.connect(x).finalizeAfterTimeout()).to.be.revertedWith("AM: window still open");
      const receipt=await transact(contract.connect(x).finalizeAfterTimeout(),"unanswered timeout at deadline + 1");
      const e=audit(receipt,"breach_confirmed"); expect(e.evidence_hash).to.equal(evidence);
      expect(e.state).to.equal(3); await flags(true);
      current.expected_reverts.push("timeout at exact deadline");
    });
    test("LC12","timeout never overrides a filed challenge; reviewer can decide later",async()=>{
      await hold(); await transact(contract.connect(a).submitChallenge(challengeEvidence),"challenge");
      const start=await contract.challengeStart(); await time.setNextBlockTimestamp(start+86401n);
      await expect(contract.connect(x).finalizeAfterTimeout()).to.be.revertedWith("AM: challenge awaiting review");
      expect(await contract.currentState()).to.equal(2n);
      const receipt=await transact(contract.connect(r).acceptChallenge(),"review after submission deadline");
      audit(receipt,"challenge_accepted"); await flags(false);
      current.expected_reverts.push("challenge awaiting review");
    });
  });
}

describe("Negative controls: deliberately faulty IR must be detectable",function () {
  let d,a,r,x;
  before(async()=>{[d,a,r,x]=await ethers.getSigners();});
  async function deploy(name) {
    const f=await ethers.getContractFactory(name);
    const c=await f.deploy(d.address,a.address,r.address,caseId,sourceHash,machine);
    await c.waitForDeployment(); return c;
  }
  async function freeze(c) {
    return (await c.connect(r).submitRecord(caseId,sourceHash,machine,315,960,900,evidence)).wait();
  }
  it("detects inclusive oxygen boundary mutant",async()=>{
    const c=await deploy("MutantOxygenInclusive");
    const rc=await (await c.connect(r).submitRecord(caseId,sourceHash,machine,285,960,1000,evidence)).wait();
    expect(await c.currentState()).to.equal(0n); // violates the correct LC05 requirement
    results.mutation_controls.push({name:"MutantOxygenInclusive",detected:true,
      violated_check:"LC05",observation:"1000 ppm incorrectly accepted",receipt:await receiptRecord(c,rc)});
  });
  it("detects timeout override mutant",async()=>{
    const c=await deploy("MutantTimeoutOverride"); await freeze(c);
    await c.connect(a).submitChallenge(challengeEvidence);
    const start=await c.challengeStart(); await time.setNextBlockTimestamp(start+86401n);
    const rc=await (await c.connect(x).finalizeAfterTimeout()).wait();
    expect(await c.currentState()).to.equal(3n); // violates correct LC12
    results.mutation_controls.push({name:"MutantTimeoutOverride",detected:true,
      violated_check:"LC12",observation:"filed challenge incorrectly closed by timeout",receipt:await receiptRecord(c,rc)});
  });
  it("detects missing execution evidence hash mutant",async()=>{
    const c=await deploy("MutantMissingEvidence"); const rc=await freeze(c);
    const e=decode(c,rc).find(l=>l.event==="AuditEvidence");
    expect(e.evidence_hash).to.equal(ethers.ZeroHash);
    results.mutation_controls.push({name:"MutantMissingEvidence",detected:true,
      violated_check:"AC.freeze",observation:"event and clause exist but evidence hash is empty",receipt:await receiptRecord(c,rc)});
  });
});
