import sys, subprocess, uuid, os, json, time

template, stack_name, *parameter_pairs = sys.argv[1:]
region = os.environ.get("AWS_REGION", "ap-south-1")
parameters = []
for pair in parameter_pairs:
    key, value = pair.split("=", 1)
    parameters.append({"ParameterKey": key, "ParameterValue": value})
def aws(*args, check=True):
    return subprocess.run(["aws", *args, "--region", region], check=check, text=True, capture_output=True)
stack_info = aws(
    "cloudformation",
    "describe-stacks",
    "--stack-name", stack_name,
    "--query", "Stacks[0].StackStatus",
    "--output", "text",
    check=False
)

exists = stack_info.returncode == 0

if exists:
    status = stack_info.stdout.strip()

    if status == "ROLLBACK_FAILED":
        print(f"Stack {stack_name} is in ROLLBACK_FAILED. Recovering automatically...")

        aws(
            "cloudformation", "delete-stack",
            "--stack-name", stack_name
        )

        aws(
            "cloudformation", "wait", "stack-delete-complete",
            "--stack-name", stack_name
        )

        exists = False

    elif status in ("DELETE_IN_PROGRESS", "DELETE_COMPLETE"):
        aws(
            "cloudformation", "wait", "stack-delete-complete",
            "--stack-name", stack_name
        )
        exists = False

kind = "UPDATE" if exists else "CREATE"name = f"m2-{uuid.uuid4().hex[:12]}"
cmd = ["cloudformation", "create-change-set", "--stack-name", stack_name,
       "--template-body", f"file://{template}", "--change-set-name", name,
       "--change-set-type", kind, "--capabilities", "CAPABILITY_NAMED_IAM",
       "--parameters"] + [f"ParameterKey={p['ParameterKey']},ParameterValue={p['ParameterValue']}" for p in parameters]
result = aws(*cmd, check=False)
if result.returncode:
    print(result.stderr)
    raise SystemExit(result.returncode)
for _ in range(90):
    info = aws("cloudformation", "describe-change-set", "--stack-name", stack_name,
               "--change-set-name", name, "--output", "json", check=False)
    if info.returncode == 0:
        data = json.loads(info.stdout)
        if data["Status"] in ("CREATE_COMPLETE", "FAILED"):
            break
    time.sleep(5)
else:
    raise SystemExit("Timed out waiting for Change Set creation")
print(json.dumps({"stack": stack_name, "type": kind, "status": data["Status"],
                  "reason": data.get("StatusReason"), "changes": [
                      {"action": c["ResourceChange"]["Action"],
                       "logicalId": c["ResourceChange"]["LogicalResourceId"],
                       "type": c["ResourceChange"]["ResourceType"]}
                      for c in data.get("Changes", [])]}, indent=2))
if data["Status"] != "CREATE_COMPLETE":
    reason = data.get("StatusReason", "")
    if "didn't contain changes" in reason or "No updates are to be performed" in reason:
        print("No changes to deploy.")
        raise SystemExit(0)
    raise SystemExit("Change Set failed; see reason above.")
aws("cloudformation", "execute-change-set", "--stack-name", stack_name, "--change-set-name", name)
waiter = "stack-create-complete" if kind == "CREATE" else "stack-update-complete"
aws("cloudformation", "wait", waiter, "--stack-name", stack_name)
print(f"Stack {stack_name} deployed successfully.")
