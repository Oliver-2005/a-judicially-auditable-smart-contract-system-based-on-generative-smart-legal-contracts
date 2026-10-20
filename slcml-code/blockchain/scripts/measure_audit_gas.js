const { ethers, network } = require('hardhat');
const fs = require('fs');
const path = require('path');
const assert = require('assert/strict');

async function main() {
  const sourceHash = ethers.keccak256(fs.readFileSync(path.join(__dirname, '../am/source_facts.json')));
  const caseId = ethers.encodeBytes32String('AMB2022-01-AMMT-B6');
  const machine = ethers.id('AMMT');
  const evidence = ethers.id('test-assertion:nominal-or-injected-record');
  const challengeEvidence = ethers.id('test-challenge:offchain-evidence-reference');
  const rows = [];
  for (const name of ['ReferenceCandidate', 'ClaudeCandidate', 'GeminiCandidate']) {
    await network.provider.send('hardhat_reset');
    const [provider, analyst, reviewer] = await ethers.getSigners();
    const factory = await ethers.getContractFactory(name);
    const contract = await factory.deploy(provider.address, analyst.address, reviewer.address, caseId, sourceHash, machine);
    await contract.waitForDeployment();
    const deployment = await contract.deploymentTransaction().wait();
    const freeze = await (await contract.connect(reviewer).submitRecord(caseId, sourceHash, machine, 315, 960, 900, evidence)).wait();
    const challenge = await (await contract.connect(analyst).submitChallenge(challengeEvidence)).wait();
    const rejection = await (await contract.connect(reviewer).rejectChallenge()).wait();
    assert.equal(await contract.currentState(), 3n);
    const receipts = [freeze, challenge, rejection];
    const events = receipts.flatMap(receipt => receipt.logs.flatMap(log => {
      try {
        const event = contract.interface.parseLog(log);
        return event?.name === 'AuditEvidence' ? [{ phase: event.args.phase,
          clause: event.args.clauseId, evidence: event.args.evidenceHash }] : [];
      } catch { return []; }
    }));
    assert.deepEqual(events.map(event => event.phase), ['freeze', 'challenge_submitted', 'breach_confirmed']);
    assert(events.every(event => event.clause === 'Clause_3.2' && event.evidence !== ethers.ZeroHash));
    rows.push({ implementation: name, deployment_gas: deployment.gasUsed.toString(),
      audit_path_gas: receipts.reduce((sum, receipt) => sum + receipt.gasUsed, 0n).toString(),
      transactions: receipts.map((receipt, index) => ({ stage: ['freeze', 'challenge', 'disposition'][index],
        transaction_hash: receipt.hash, gas: receipt.gasUsed.toString() })), audit_events: events });
  }
  const output = process.env.SLCML_RUN_OUTPUT;
  if (output) {
    fs.mkdirSync(output, { recursive: true });
    fs.writeFileSync(path.join(output, 'audit_gas.json'), JSON.stringify(rows, null, 2) + '\n');
  }
  console.log(JSON.stringify(rows, null, 2));
}

main().catch(error => { console.error(error); process.exitCode = 1; });

