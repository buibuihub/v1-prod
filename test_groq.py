from server import run_test

if __name__ == '__main__':
    import sys
    prompt = ' '.join(sys.argv[1:]) or 'hi'
    run_test(prompt)
